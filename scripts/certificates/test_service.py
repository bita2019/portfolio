import functools
import http.server
import threading
from datetime import datetime, timezone
from unittest import mock

import pymupdf
import pytest

import fetch
import service
from test_extract import GERMAN, TUV, make_pdf


@pytest.fixture
def client():
    return service.app.test_client()


@pytest.fixture
def local_server(tmp_path, monkeypatch):
    """Serve tmp_path over HTTP on localhost, with the SSRF address checks switched off."""
    monkeypatch.setenv("ALLOW_PRIVATE_HOSTS", "1")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "/cert.pdf")
                self.end_headers()
            else:
                super().do_GET()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_certificate_url_end_to_end(client, tmp_path, local_server):
    make_pdf(tmp_path / "cert.pdf", TUV)
    r = client.post("/extract", json={"url": f"{local_server}/cert.pdf?utm_source=chatgpt.com"})
    body = r.get_json()
    assert r.status_code == 200
    assert body["kind"] == "certificate"
    assert body["source"]["canonicalUrl"].endswith("/cert.pdf") and body["source"]["strippedParameters"] == ["utm_source"]
    assert body["certificate"]["standard"] == "DIN EN ISO 9001:2015" and "text" not in body["certificate"]
    assert body["certificate"]["validUntil"] == "2027-05-21T00:00:00+00:00"
    assert body["validation"]["status"] in ("valid", "expired") and not body["validation"]["passed"] is None


def test_validation_status_uses_dates():
    from extract import extract_certificate
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as d:
        lines = [l.replace("fuer", "f\u00fcr").replace("gueltig", "g\u00fcltig") for l in GERMAN]
        c = extract_certificate(make_pdf(pathlib.Path(d) / "c.pdf", lines))
    v = service.validate_certificate(c, datetime(2026, 11, 6, tzinfo=timezone.utc))
    assert v["status"] == "valid" and v["passed"] and 170 < v["daysRemaining"] < 200
    v = service.validate_certificate(c, datetime(2028, 1, 1, tzinfo=timezone.utc))
    assert v["status"] == "expired" and not v["passed"]
    v = service.validate_certificate(c, datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert v["status"] == "not_yet_valid"


def test_report_url_returns_document_metadata(client, tmp_path, local_server):
    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((60, 80), "Sustainability Statement 2024" if i == 0 else f"Chapter {i}: ESRS E1 climate, GRI 305", fontsize=12)
    doc.set_toc([[1, "Climate", 2], [1, "Water", 3]])
    doc.save(tmp_path / "sustainability-statement-2024-en.pdf")
    r = client.post("/extract", json={"url": f"{local_server}/sustainability-statement-2024-en.pdf"})
    body = r.get_json()
    assert r.status_code == 200 and body["kind"] == "document" and "certificate" not in body
    assert body["source"]["year"] == 2024 and body["source"]["language"] == "en"
    assert body["source"]["documentType"] == "sustainability statement"
    assert body["document"]["reportingYear"] == 2024 and body["document"]["pages"] == 4
    assert body["document"]["outline"] == ["Climate", "Water"]
    assert body["document"]["frameworks"] == {"ESRS": 3, "GRI": 3}
    assert body["validation"]["passed"]


def test_redirects_are_followed(client, tmp_path, local_server):
    make_pdf(tmp_path / "cert.pdf", TUV)
    body = client.post("/extract", json={"url": f"{local_server}/redirect"}).get_json()
    assert body["source"]["redirects"] == [f"{local_server}/redirect"] and body["kind"] == "certificate"


def test_non_pdf_and_missing_are_rejected(client, tmp_path, local_server):
    (tmp_path / "page.pdf").write_text("<html><head><title>Page Not Found</title></head></html>")
    r = client.post("/extract", json={"url": f"{local_server}/page.pdf"})
    assert r.status_code == 415 and 'titled "Page Not Found"' in r.get_json()["error"]
    assert client.post("/extract", json={"url": f"{local_server}/nope.pdf"}).status_code == 502
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.4 garbage")
    assert client.post("/extract", json={"url": f"{local_server}/bad.pdf"}).status_code == 422


def test_size_limit(client, tmp_path, local_server, monkeypatch):
    make_pdf(tmp_path / "cert.pdf", TUV)
    monkeypatch.setattr(fetch, "MAX_BYTES", 100)
    assert client.post("/extract", json={"url": f"{local_server}/cert.pdf"}).status_code == 413


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/a.pdf", "http://localhost/a.pdf", "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5/a.pdf", "http://[::1]/a.pdf", "http://192.168.1.1/a.pdf",
])
def test_private_addresses_are_blocked(client, url):
    assert client.post("/extract", json={"url": url}).status_code == 403


@pytest.mark.parametrize("url,status", [
    ("file:///etc/passwd", 400), ("ftp://example.com/a.pdf", 400), ("not a url", 400),
    ("https://example.com:8443/a.pdf", 403),
])
def test_bad_urls(client, url, status):
    assert client.post("/extract", json={"url": url}).status_code == status


def test_bad_request_body(client):
    assert client.post("/extract", json={}).status_code == 400
    assert client.post("/extract", data="x").status_code == 400


def test_redirect_to_private_address_is_blocked(client):
    redirect = mock.Mock(is_redirect=True, status_code=302, headers={"Location": "http://169.254.169.254/latest"})
    redirect.close = lambda: None
    real = fetch.socket.getaddrinfo

    def resolve(host, *args, **kwargs):  # only the first hop pretends to be a public host
        return [(2, 1, 6, "", ("8.8.8.8", 443))] if host == "public.example" else real(host, *args, **kwargs)

    with mock.patch("fetch.socket.getaddrinfo", side_effect=resolve), \
         mock.patch("fetch.requests.Session.get", return_value=redirect):
        r = client.post("/extract", json={"url": "https://public.example/a.pdf"})
    assert r.status_code == 403


def test_allowed_hosts(client, monkeypatch):
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)  # no proxy: names are resolved locally
    monkeypatch.setenv("ALLOWED_HOSTS", "georgfischer.com")
    assert client.post("/extract", json={"url": "https://evil.example/a.pdf"}).status_code == 403
    with mock.patch("fetch.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
        # allowed host name, but it resolves to loopback: still refused
        assert client.post("/extract", json={"url": "https://www.georgfischer.com/a.pdf"}).status_code == 403


def test_api_key(client, monkeypatch):
    monkeypatch.setenv("SERVICE_API_KEY", "secret")
    assert client.get("/health").status_code == 200
    assert client.post("/extract", json={"url": "https://x.example/a.pdf"}).status_code == 401
    assert client.post("/extract", json={"url": "file:///x"}, headers={"X-API-Key": "secret"}).status_code == 400


def test_proxied_environment_skips_local_dns_but_still_blocks_literals(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    with mock.patch("fetch.socket.getaddrinfo", side_effect=OSError("no local DNS")) as dns:
        fetch.check_url("https://www.example.com/a.pdf")  # name: left to the proxy, no local lookup
        dns.assert_not_called()
        for bad in ("https://169.254.169.254/x", "https://10.0.0.1/x", "https://localhost/x", "https://db.internal/x"):
            with pytest.raises(fetch.FetchError) as e:
                fetch.check_url(bad)
            assert e.value.status == 403


def _titled_pdf(path, metadata_title=None):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 60), "Annual figures at a glance", fontsize=11)
    page.insert_text((60, 120), "Engineering", fontsize=40)
    page.insert_text((60, 170), "a sustainable future 2024", fontsize=40)
    page.insert_text((60, 220), "Revenue 224m", fontsize=14)
    if metadata_title is not None:
        doc.set_metadata({"title": metadata_title})
    doc.save(path)
    return path


@pytest.mark.parametrize("meta,expected,source", [
    (None, "Engineering a sustainable future 2024", "first-page-heading"),
    ("Microsoft Word - report_final.docx", "Engineering a sustainable future 2024", "first-page-heading"),
    ("Engineering", "Engineering a sustainable future 2024", "first-page-heading"),
    ("Castings plc Sustainability Report 2024", "Castings plc Sustainability Report 2024", "pdf-metadata"),
])
def test_title_selection(tmp_path, meta, expected, source):
    from report import extract_document
    d = extract_document(_titled_pdf(tmp_path / "t.pdf", meta))
    assert (d["title"], d["titleSource"]) == (expected, source)
    assert d["pdfTitle"] == meta


def test_percent_encoded_name_with_stamped_date():
    m = fetch.url_metadata("https://www.matfoundrygroup.com/res/Group%20ESG%20Report%202023%202024-12-17.pdf")
    assert m["fileName"] == "Group ESG Report 2023 2024-12-17.pdf"
    assert (m["year"], m["dateInName"], m["documentType"]) == (2023, "2024-12-17", "Group ESG Report")


def test_default_powerpoint_title_and_slide_bookmarks_are_ignored(tmp_path):
    from report import extract_document

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 60), "ANNUAL ESG REPORT 2023", fontsize=36)
    page.insert_text((60, 120), "Board message", fontsize=12)
    doc.new_page()
    doc.set_metadata({"title": "PowerPoint Presentation"})
    doc.set_toc([[1, "Slide 1", 1], [1, "Slide 2", 2]])
    doc.save(tmp_path / "p.pdf")
    d = extract_document(tmp_path / "p.pdf", "https://www.matfoundrygroup.com/res/Group%20ESG%20Report%202023.pdf")
    assert (d["title"], d["titleSource"], d["pdfTitle"]) == ("ANNUAL ESG REPORT 2023", "first-page-heading", "PowerPoint Presentation")
    assert d["outline"] == []
    assert all(c["name"] != "Group" for c in d["company"]["candidates"])
