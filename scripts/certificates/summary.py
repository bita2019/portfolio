"""The short metadata record: company, country, city, author or issuer, title, start and end date."""
import re

from location import country_of

GENERIC_AUTHOR = re.compile(r"^(admin(istrator)?|user|owner|author|unknown|microsoft.*|adobe.*|windows.*|pc|laptop|acrobat.*|word|ps|none)$", re.I)


def _author(document: dict, company: str | None) -> tuple[str | None, str | None]:
    author = (document.get("author") or "").strip()
    if len(author) >= 3 and re.search(r"[A-Za-z]", author) and not GENERIC_AUTHOR.match(author):
        return author, "author"
    return company, "issuer" if company else None


def summarize(full: dict) -> dict:
    """Boil a full extraction result down to the fields people asked for, plus notes on anything uncertain."""
    notes = []
    if full["kind"] == "certificate":
        c = full["certificate"]
        org = c["organization"]
        sites = c.get("sites") or []
        city = org["city"] or (sites[0]["city"] if len(sites) == 1 else None)
        if len(sites) > 1:
            notes.append("multiple sites: " + ", ".join(sorted({s["city"] for s in sites if s["city"]})))
        title = f"{c['standard']} certificate" if c["standard"] else "Certificate"
        return {
            "companyName": org["name"], "country": country_of(org["country"]) or org["country"], "city": city,
            "authorOrIssuer": c["certificationBody"] or c["signedBy"], "authorOrIssuerRole": "issuer",
            "reportTitle": title, "reportingPeriod": None,
            "startDate": c["validFrom"].date().isoformat() if c["validFrom"] else None,
            "endDate": c["validUntil"].date().isoformat() if c["validUntil"] else None,
            "notes": notes,
        }

    d = full["document"]
    company, loc, dates = d["company"], d["location"], d["dates"]
    author, role = _author(d, company["name"])
    if company["confidence"] != "high":
        notes.append(f"company name: {company['confidence']} confidence ({company['source']})")
    if not loc["country"]:
        notes.append("country not found")
    elif loc["countryEvidence"] in ("web address ending", "VAT number prefix"):
        notes.append(f"country taken from the {loc['countryEvidence']}")
    if not loc["city"]:
        notes.append("city not found")
    if role == "author":
        notes.append("author is the PDF's author field")
    if dates["basis"] == "only the end date is stated":
        notes.append(f"start date not stated; end date from \"{dates['text']}\"")
    elif dates["basis"] != "stated":
        notes.append("start and end date " + dates["basis"])
    if d["titleSource"] not in ("pdf-metadata", "first-page-heading"):
        notes.append(f"title taken from {d['titleSource']}")
    return {
        "companyName": company["name"], "country": loc["country"], "city": loc["city"],
        "authorOrIssuer": author, "authorOrIssuerRole": role, "reportTitle": d["title"],
        "reportingPeriod": d["scope"]["reportingPeriod"],
        "startDate": dates["startDate"], "endDate": dates["endDate"], "notes": notes,
    }
