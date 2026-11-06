"""Extract structured metadata from certificate PDFs (ISO 9001 style)."""
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
# ISO (2024-05-22), German (22.05.2024) or English (June 14, 2025) dates
DATE = rf"\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\.\d{{1,2}}\.\d{{4}}|(?:{MONTHS})\s+\d{{1,2}},\s*\d{{4}}"
ISO_DATE = DATE
STANDARD = re.compile(r"(?:DIN\s+)?(?:EN\s+)?(?:ISO(?:/\w+)?|IATF)\s*\d{3,5}(?::\d{4}(?:-\d{2})?)?", re.I)


def _section(text: str, start: str, end: str) -> str | None:
    m = re.search(rf"(?:{start})\s*([\s\S]*?)\s*(?:{end})", text, re.I)
    return m.group(1).strip() if m else None


def _lines(s: str | None) -> list[str]:
    return [l.strip() for l in (s or "").split("\n") if l.strip()]


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s.strip())
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%B %d, %Y", "%B %d,%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _first(pattern: str, text: str, flags: int = re.I) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


SITE = re.compile(r"^(?P<street>.*?)(?:,|\s+in)\s+(?:[A-Z]{1,2}-)?(?P<postal>\d{4,5})\s+(?P<city>.+)$")


def _sites(lines: list[str]) -> list[dict]:
    sites = []
    for line in lines:
        m = SITE.match(line)
        sites.append(
            {"street": m["street"].strip(), "postalCode": m["postal"], "city": m["city"].strip()}
            if m
            else {"street": line, "postalCode": None, "city": None}
        )
    return sites


def extract_certificate(path: str | Path) -> dict:
    """Handles TÜV-style certificates (English or German) and multi-site environmental-verifier certificates."""
    path = Path(path)
    data = path.read_bytes()
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = "\n".join(re.sub(r"[ \t]+", " ", l).strip() for l in text.replace("\r", "").splitlines()).strip()
    meta = reader.metadata
    german = bool(re.search(r"bescheinigt|Geltungsbereich|Zertifizierungsstelle", text))

    name = street = postal = city = country = None
    sites: list[dict] = []
    scope = None
    signed_by = None
    body = _first(r"(?:Certification Body|Zertifizierungsstelle)\s+(?:of|der)\s+([^\n]+)", text)

    if re.search(r"at their sites", text, re.I):
        # Environmental-verifier layout: name over several lines, then a list of sites.
        name = " ".join(_lines(_section(text, r"Management System of", r"at their sites"))) or None
        sites = _sites(_lines(_section(text, r"at their sites", r"has been evaluated")))
        verifier = list(re.finditer(r"^(.+)\n(?:\s*\n)*accredited environmental verifier", text, re.M | re.I))
        signed_by = verifier[-1].group(1).strip() if verifier else None
        verifier_id = _first(r"registration number\s+(\S+)", text)
        if signed_by:
            body = f"{signed_by} (accredited environmental verifier{f' {verifier_id}' if verifier_id else ''})"
        if len(sites) == 1:
            street, postal, city = sites[0]["street"], sites[0]["postalCode"], sites[0]["city"]
    else:
        holder = _lines(_section(text, r"certifies that the organization|bescheinigt, dass die Organisation",
                                 r"for the scope|f\u00fcr den Geltungsbereich"))
        city_m = re.match(r"^(\d{4,5})\s+(.+)$", holder[-2]) if len(holder) >= 2 else None
        name = holder[0] if holder else None
        street = ", ".join(holder[1:-2]) or None
        postal, city = (city_m.group(1), city_m.group(2)) if city_m else (None, None)
        country = holder[-1] if len(holder) > 1 else None
        scope = _section(text, r"for the scope|f\u00fcr den Geltungsbereich",
                         r"has established|ein\s+\S*managementsystem")
        scope = re.sub(r"\s*\n\s*", " ", scope) if scope else None
        signed_by = _first(r"^(.+)\n(?:Head of Certification Body|Leiter der Zertifizierungsstelle)", text, re.M)

    validity = re.search(rf"(?:valid\s+from|g\u00fcltig\s+vom)\s+({DATE})\s+(?:until|bis)\s+({DATE})", text, re.I)
    issued = re.search(rf"^([^\W\d_][\w .-]*?),\s*({DATE})\s*$", text, re.M)
    standard = STANDARD.search(text)

    return {
        "fileName": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "language": "de" if german else "en",
        "registrationNo": _first(r"(?:Registration No\.?|Zertifikat-Registrier-Nr\.?):\s*([^/\n]+?)\s*(?:/|\n)", text)
        or _first(r"Reg\.-No\.?\s+(\S+)", text),
        "orderNo": _first(r"(?:Order No\.?|Auftrags-Nr\.?):?\s*(\S+)", text),
        "certificationBody": body,
        "organization": {
            "name": name,
            "street": street,
            "postalCode": postal,
            "city": city,
            "country": country,
        },
        "sites": sites,
        "scope": scope,
        "standard": re.sub(r"\s+", " ", standard.group(0)) if standard else None,
        "validFrom": _date(validity.group(1)) if validity else None,
        "validUntil": _date(validity.group(2)) if validity else None,
        "issuedPlace": issued.group(1).strip() if issued else None,
        "issuedDate": _date(issued.group(2)) if issued else None,
        "signedBy": signed_by,
        "pdf": {
            "pages": len(reader.pages),
            "author": (meta.author if meta else None) or None,
            "creator": (meta.creator if meta else None) or None,
            "createdAt": meta.creation_date if meta else None,
        },
        "text": text,
    }


def embedding_text(c: dict) -> str:
    """Text that gets embedded: the fields people actually search by."""
    org = c["organization"]
    address = ", ".join(filter(None, [org["street"], org["postalCode"], org["city"], org["country"]]))
    sites = "; ".join(
        ", ".join(filter(None, [x["street"], x["postalCode"], x["city"]])) for x in c.get("sites", [])
    )
    parts = [
        org["name"],
        address,
        sites and f"Sites: {sites}",
        c["standard"] and f"Standard: {c['standard']}",
        c["scope"] and f"Scope: {c['scope']}",
        c["certificationBody"] and f"Certified by {c['certificationBody']}",
    ]
    return "\n".join(p for p in parts if p)
