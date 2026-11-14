#!/usr/bin/env python3
"""Validation service: POST a URL, get back validated metadata.

    pip install -r requirements.txt
    python service.py                     # http://127.0.0.1:8000

    curl -X POST localhost:8000/extract -H 'content-type: application/json' \
         -d '{"url": "https://example.com/cert.pdf"}'          # short record
    curl -X POST 'localhost:8000/extract?detail=full' ...        # everything the extractor found

Env: ALLOWED_HOSTS (comma list, recommended), SERVICE_API_KEY (require X-API-Key), MAX_PDF_MB, PORT.
"""
import hmac
import os
from datetime import datetime

from flask import Flask, jsonify, request

from analyze import looks_like_certificate, process, validate_certificate, validate_document  # noqa: F401
from fetch import FetchError, check_url
from summary import summarize

app = Flask(__name__)
app.json.sort_keys = False
app.json.default = lambda o: o.isoformat() if isinstance(o, datetime) else str(o)


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
        result = process(url.strip())
        if request.args.get("detail") == "full":  # everything the extractor found, not just the short record
            return jsonify({"url": url.strip(), "status": "read", "metadata": summarize(result), **result})
        return jsonify({"url": url.strip(), "status": "read", **summarize(result)})
    except FetchError as error:
        return jsonify(error=str(error)), error.status


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", 8000)))
