"""Finding a report on the company's own website when the link we were given does not work."""
import functools
import http.server
import threading
from unittest import mock

import pymupdf
import pytest

import analyze
import discover
import extract_metadata as cli
from fetch import FetchError
from test_extract import make_pdf


def pdf(path, text, year="2024"):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), f"{text} {year}", fontsize=24)
    page.insert_text((50, 160), "This report covers the period from 1 January to 31 December " + year, fontsize=9)
    doc.save(path)
    return path


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A small company website: a home page, a sustainability page with several PDFs, and one blocked file."""
    monkeypatch.setenv("ALLOW_PRIVATE_HOSTS", "1")
    (tmp_path / "files").mkdir()
    pdf(tmp_path / "files" / "Sustainability-Report-2022.pdf", "Sustainability Report", "2022")
    pdf(tmp_path / "files" / "Sustainability-Report-2024-final.pdf", "Sustainability Report", "2024")
    pdf(tmp_path / "files" / "Supplier-Code-of-Conduct-2024.pdf", "Supplier Code of Conduct", "2024")
    pdf(tmp_path / "files" / "Annual-Report-2024.pdf", "Annual Report", "2024")
    (tmp_path / "index.html").write_text('<html><body><a href="/about">About</a> <a href="/sustainability">Sustainability</a></body></html>')
    (tmp_path / "sustainability").write_text(
        '<html><body><h1>Reports</h1><a href="/files/Sustainability-Report-2022.pdf">2022 report</a>'
        '<a href="/files/Supplier-Code-of-Conduct-2024.pdf">Supplier code</a>'
        '<a href="/files/Sustainability-Report-2024-final.pdf">Sustainability Report 2024</a>'
        '<a href="/files/Annual-Report-2024.pdf">Annual report</a></body></html>')
    (tmp_path / "about").write_text("<html><body>nothing here</body></html>")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def guess_type(self, path):
            return "text/html" if not path.endswith(".pdf") else "application/pdf"

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_dead_link_is_resolved_through_the_companys_site(site):
    result = analyze.process(f"{site}/getmedia/1234/Sustainability_Report_2024_web.pdf")
    assert result["source"]["resolvedUrl"] == f"{site}/files/Sustainability-Report-2024-final.pdf"
    assert result["source"]["requestedUrl"].endswith("Sustainability_Report_2024_web.pdf")
    assert result["document"]["reportingYear"] == 2024


def test_the_entry_records_both_addresses_and_says_so_in_the_notes(site):
    entry = cli.extract_one("url", f"{site}/old/Sustainability_Report_2024.pdf")
    assert entry["status"] == "read" and entry["url"].endswith("Sustainability-Report-2024-final.pdf")
    assert entry["requestedUrl"].endswith("old/Sustainability_Report_2024.pdf")
    assert "found on the company's website" in entry["notes"][0]
    assert cli.to_contract(entry)["url"] == entry["url"]  # the contract carries the address that was actually read


def test_the_right_year_is_chosen_and_other_documents_are_not(site):
    found = discover.find_candidates(f"{site}/x/Sustainability_Report_2024.pdf")
    assert found[0][1].endswith("Sustainability-Report-2024-final.pdf")
    assert not any("Supplier-Code" in url or "2022" in url for _, url, _ in found)
    found22 = discover.find_candidates(f"{site}/x/Sustainability_Report_2022.pdf")
    assert found22[0][1].endswith("Sustainability-Report-2022.pdf")


def test_a_pdf_for_the_wrong_year_or_topic_is_never_accepted(tmp_path):
    hint = {"year": 2024, "tokens": set()}
    assert discover.looks_like_the_report(pdf(tmp_path / "a.pdf", "Sustainability Report", "2024"), hint)
    assert not discover.looks_like_the_report(pdf(tmp_path / "b.pdf", "Sustainability Report", "2019"), hint)
    assert not discover.looks_like_the_report(pdf(tmp_path / "c.pdf", "Quarterly results", "2024"), hint)


def test_nothing_on_the_site_gives_an_honest_message(site):
    with pytest.raises(FetchError) as error:
        analyze.process(f"{site}/getmedia/9/Environmental_Report_2031.pdf")
    assert "no matching report was found" in str(error.value) or "did not match" in str(error.value)


def test_a_report_found_but_blocked_is_not_called_unavailable(site):
    real = discover.download

    def blocked(url, dest):
        if "2024-final" in url:
            raise FetchError("The server answered HTTP 403.", 502)
        return real(url, dest)

    with mock.patch("discover.download", blocked), mock.patch("analyze.discover_report", functools.partial(discover.discover_report, fetch_pdf=blocked)):
        with pytest.raises(FetchError) as error:
            analyze.process(f"{site}/getmedia/1/Sustainability_Report_2024.pdf")
    assert error.value.status == 403 and "refuses automated downloads" in str(error.value) and "Sustainability-Report-2024-final.pdf" in str(error.value)


def test_discovery_can_be_switched_off(site):
    with pytest.raises(FetchError):
        analyze.process(f"{site}/getmedia/1/Sustainability_Report_2024.pdf", discover=False)


def test_start_pages_and_registrable_domains():
    assert discover.registrable_domain("cdn.arcelormittal.com") == "arcelormittal.com"
    assert discover.registrable_domain("castings.plc.uk") == "castings.plc.uk"
    assert discover.registrable_domain("www.example.co.uk") == "example.co.uk"
    pages = discover.start_pages("https://cdn.arcelormittal.com/media/x/report.pdf")
    assert pages[0] == "https://cdn.arcelormittal.com/" and "https://corporate.arcelormittal.com/" in pages and "https://www.arcelormittal.com/" in pages


def test_links_are_read_from_anchors_and_resolved(tmp_path):
    html = '<a href="/a.pdf">First</a> <a href="docs/b.pdf?x=1">Second <b>report</b></a> <a href="#top">skip</a> <a href="mailto:x@y.z">m</a>'
    assert discover.extract_links(html, "https://example.com/sustainability/") == [
        ("https://example.com/a.pdf", "First"), ("https://example.com/sustainability/docs/b.pdf?x=1", "Second report")]
