"""The short metadata record: company, country, city, author or issuer, title, start and end date."""
import re

from location import country_of

def _issuer(company: str | None) -> tuple[str | None, str | None]:
    """Only the report itself can name an author. The PDF's author field is software or an employee's name, so it is not
    used: the issuer is the company that published the report."""
    return company, "issuer" if company else None


def summarize(full: dict) -> dict:
    """Boil a full extraction result down to the fields people asked for, plus notes on anything uncertain."""
    notes = []
    source = full.get("source") or {}
    if source.get("resolvedUrl"):
        notes.append(f"the link given did not work ({source['originalError'].rstrip('.')}); the report was found on the company's website: {source['resolvedUrl']}")
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
    author, role = _issuer(company["name"])
    if company["confidence"] != "high":
        notes.append(f"company name: {company['confidence']} confidence ({company['source']})")
    if not loc["country"]:
        notes.append("country not found")
    elif loc["countryEvidence"] in ("web address ending", "VAT number prefix"):
        notes.append(f"country taken from the {loc['countryEvidence']}")
    if not loc["city"]:
        notes.append("city not found")
    basis = dates["basis"]
    if basis.startswith("end date stated"):
        notes.append(f"start date derived (assumption): the report states only \"{dates['text']}\", so the start is taken as the first day of that 12-month year")
    elif basis == "only the end date is stated":
        notes.append(f"start date not stated: the report gives only a year end (\"{dates['text']}\")")
    elif basis == "stated (calendar year)":
        notes.append(f"dates are the calendar year the report names (\"{dates['text']}\"): 1 January to 31 December")
    elif basis == "stated (whole months)":
        notes.append(f"dates are the first and last day of the months the report names (\"{dates['text']}\")")
    elif dates["startDate"] is None:
        notes.append("start and end date " + basis)
    if not d["titleSource"].startswith(("pdf-metadata", "first-page-heading")):
        notes.append(f"title taken from {d['titleSource']}")
    return {
        "companyName": company["name"], "country": loc["country"], "city": loc["city"],
        "authorOrIssuer": author, "authorOrIssuerRole": role, "reportTitle": d["title"],
        "reportingPeriod": d["scope"]["reportingPeriod"],
        "startDate": dates["startDate"], "endDate": dates["endDate"], "notes": notes,
    }
