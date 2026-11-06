#!/usr/bin/env python3
"""Validation service: POST a URL, get back validated metadata.

    pip install -r requirements.txt
    python service.py                     # http://127.0.0.1:8000

    curl -X POST localhost:8000/extract -H 'content-type: application/json' \
         -d '{"url": "https://example.com/cert.pdf"}'

Env: ALLOWED_HOSTS (comma list, recommended), SERVICE_API_KEY (require X-API-Key), MAX_PDF_MB, PORT.
"""
import hmac
import os
import re
import tempfile
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from extract import extract_certificate
from fetch import FetchError, download, url_metadata, check_url
from report import extract_document

app = Flask(__name__)
app.json.sort_keys = False
app.json.default = lambda o: o.isoformat() if isinstance(o, datetime) else str(o)


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


def process(url: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    source = url_metadata(url)
    with tempfile.TemporaryDirectory() as tmp:
        path, fetched = download(url, tmp)
        try:
            document = extract_document(path)
            certificate = extract_certificate(path) if looks_like_certificate(document) else None
        except Exception as error:
            raise FetchError(f"The PDF could not be read: {error}", 422)

    result = {"source": {**source, **fetched}, "kind": "certificate" if certificate else "document"}
    if certificate:
        certificate.pop("text", None)
        result["certificate"] = certificate
        result["validation"] = validate_certificate(certificate, now)
    result["document"] = document
    if not certificate:
        result["validation"] = validate_document(document)
    return result


@app.before_request
def require_key():
    key = os.getenv("SERVICE_API_KEY")
    if key and request.endpoint != "health" and not hmac.compare_digest(request.headers.get("X-API-Key", ""), key):
        return jsonify(error="Missing or invalid API key."), 401


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/extract")
def extract():
    body = request.get_json(silent=True) or {}
    url = body.get("url")
    if not isinstance(url, str) or not url.strip():
        return jsonify(error='Send JSON like {"url": "https://…/file.pdf"}.'), 400
    try:
        check_url(url.strip())  # fail fast, before any network work
        return jsonify(process(url.strip()))
    except FetchError as error:
        return jsonify(error=str(error)), error.status


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", 8000)))
