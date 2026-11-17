"""The extraction pipeline: PDF file (or URL) in, full result out. No web framework needed."""
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from extract import extract_certificate
from discover import discover_report
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


def _worth_searching(error: FetchError) -> bool:
    """A server refusal or a non-PDF page says nothing about whether the report exists, so look for it on the company's site."""
    text = str(error)
    return "The server answered HTTP" in text or "did not return a PDF" in text


def process(url: str, now: datetime | None = None, discover: bool = True) -> dict:
    """Download a PDF from a URL (with SSRF protection) and extract everything from it.

    If the link fails, the company's own website is searched for the report before giving up (discover=False turns that off).
    """
    with tempfile.TemporaryDirectory() as tmp:
        try:
            path, fetched = download(url, tmp)
            return analyze_pdf(path, url, now, {**url_metadata(url), **fetched})
        except FetchError as error:
            if not (discover and _worth_searching(error)):
                raise
            try:
                path, fetched, official = discover_report(url, tmp)
            except FetchError as search_error:
                raise FetchError(f"{error} {search_error}", 403 if search_error.status == 403 else error.status)
            source = {**url_metadata(url), **fetched, "requestedUrl": url, "resolvedUrl": official, "originalError": str(error)}
            return analyze_pdf(path, url, now, source)
