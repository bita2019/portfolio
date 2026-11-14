"""The extraction pipeline: PDF file (or URL) in, full result out. No web framework needed."""
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from extract import extract_certificate
from fetch import FetchError, download, url_metadata
from report import extract_document


def looks_like_certificate(document: dict) -> bool:
    return document["pages"] <= 5 and bool(re.search(r"certificat|zertifikat", document["firstPageText"], re.I))


def validate_certificate(c: dict, now: datetime) -> dict:
    checks = [
        {"check": "organization_found", "ok": bool(c["organization"]["name"])},
        {"check": "standard_found", "ok": bool(c["standard"])},
        {"check": "validity_dates_found", "ok": bool(c["validFrom"] and c["validUntil"])},
    ]
    status, days = "unknown", None
    if c["validFrom"] and c["validUntil"]:
        end = c["validUntil"].replace(hour=23, minute=59, second=59)
        days = (end - now).days
        status = "not_yet_valid" if c["validFrom"] > now else "expired" if end < now else "valid"
        checks.append({"check": "currently_valid", "ok": status == "valid", "detail": status})
    return {"passed": all(x["ok"] for x in checks), "status": status, "daysRemaining": days, "checks": checks}


def validate_document(d: dict) -> dict:
    checks = [
        {"check": "title_found", "ok": bool(d["title"])},
        {"check": "reporting_year_found", "ok": d["reportingYear"] is not None},
    ]
    return {"passed": all(x["ok"] for x in checks), "checks": checks}


def analyze_pdf(path: str | Path, url: str | None = None, now: datetime | None = None, source: dict | None = None) -> dict:
    """Extract everything from one PDF on disk. `url` (if known) helps find the company name."""
    now = now or datetime.now(timezone.utc)
    path = Path(path)
    try:
        document = extract_document(path, url)
        certificate = extract_certificate(path) if looks_like_certificate(document) else None
    except Exception as error:
        raise FetchError(f"The PDF could not be read: {error}", 422)

    result = {"source": source or {"fileName": path.name}, "kind": "certificate" if certificate else "document"}
    if certificate:
        certificate.pop("text", None)
        result["certificate"] = certificate
        name = certificate["organization"]["name"]
        if name:  # a certificate states its holder outright, which beats guessing from the URL
            document["company"] = {"name": name, "shortName": None, "source": "certificate", "confidence": "high", "candidates": []}
        result["validation"] = validate_certificate(certificate, now)
    result["document"] = document
    if not certificate:
        result["validation"] = validate_document(document)
    return result


def process(url: str, now: datetime | None = None) -> dict:
    """Download a PDF from a URL (with SSRF protection) and extract everything from it."""
    with tempfile.TemporaryDirectory() as tmp:
        path, fetched = download(url, tmp)
        return analyze_pdf(path, url, now, {**url_metadata(url), **fetched})
