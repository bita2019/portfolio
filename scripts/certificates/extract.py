"""Extract structured metadata from certificate PDFs (ISO 9001 style)."""
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

ISO_DATE = r"\d{4}-\d{2}-\d{2}"
STANDARD = re.compile(r"(?:DIN\s+)?(?:EN\s+)?(?:ISO(?:/\w+)?|IATF)\s*\d{3,5}(?::\d{4})?", re.I)


def _section(text: str, start: str, end: str) -> str | None:
    m = re.search(rf"{start}\s*([\s\S]*?)\s*(?:{end})", text, re.I)
    return m.group(1).strip() if m else None


def _lines(s: str | None) -> list[str]:
    return [l.strip() for l in (s or "").split("\n") if l.strip()]


def _date(s: str | None) -> datetime | None:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc) if s else None


def _first(pattern: str, text: str, flags: int = re.I) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def extract_certificate(path: str | Path) -> dict:
    path = Path(path)
    data = path.read_bytes()
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = re.sub(r"[ \t]+", " ", text.replace("\r", "")).strip()
    meta = reader.metadata

    holder = _lines(_section(text, "certifies that the organization", "for the scope"))
    city = re.match(r"^(\d{4,5})\s+(.+)$", holder[-2]) if len(holder) >= 2 else None

    validity = re.search(rf"valid from ({ISO_DATE}) until ({ISO_DATE})", text, re.I)
    issued = re.search(rf"([^\W\d_][\w .-]*?),\s*({ISO_DATE})\s*$", text, re.M)
    scope = _section(text, "for the scope", "has established")
    standard = STANDARD.search(text)

    return {
        "fileName": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "registrationNo": _first(r"Registration No\.?:\s*([^/\n]+?)\s*(?:/|\n)", text),
        "orderNo": _first(r"Order No\.?:\s*(\S+)", text),
        "certificationBody": _first(r"Certification Body\s+of\s+([^\n]+)", text),
        "organization": {
            "name": holder[0] if holder else None,
            "street": ", ".join(holder[1:-2]) or None,
            "postalCode": city.group(1) if city else None,
            "city": city.group(2) if city else None,
            "country": holder[-1] if len(holder) > 1 else None,
        },
        "scope": re.sub(r"\s*\n\s*", " ", scope) if scope else None,
        "standard": re.sub(r"\s+", " ", standard.group(0)) if standard else None,
        "validFrom": _date(validity.group(1)) if validity else None,
        "validUntil": _date(validity.group(2)) if validity else None,
        "issuedPlace": issued.group(1).strip() if issued else None,
        "issuedDate": _date(issued.group(2)) if issued else None,
        "signedBy": _first(r"^(.+)\nHead of Certification Body", text, re.M),
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
    parts = [
        org["name"],
        address,
        c["standard"] and f"Standard: {c['standard']}",
        c["scope"] and f"Scope: {c['scope']}",
        c["certificationBody"] and f"Certified by {c['certificationBody']}",
    ]
    return "\n".join(p for p in parts if p)
