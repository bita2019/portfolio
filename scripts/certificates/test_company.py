from datetime import datetime, timezone
from unittest import mock

import pytest

import service
from company import detect_company, host_label


@pytest.mark.parametrize("url,label", [
    ("https://www.fonderieariotti.com/x.pdf", "fonderieariotti"),
    ("https://castings.plc.uk/media/a.pdf", "castings"),
    ("https://waupacafoundry.com/getmedia/a.pdf", "waupacafoundry"),
    ("https://reports.georgfischer.com/a.pdf", "georgfischer"),
    ("https://www.acme.co.uk/a.pdf", "acme"),
    ("https://borgautomotive-group.com/media/x.pdf", "borgautomotivegroup"),
    ("not a url", None),
])
def test_host_label(url, label):
    assert host_label(url) == label


def test_domain_label_is_respelled_from_the_text():
    texts = ["2024 Sustainability report", "Fonderie Ariotti has made castings for 114 years. Fonderie Ariotti SpA"]
    c = detect_company("https://www.fonderieariotti.com/wp-content/uploads/Doc-04-03-EN-Report-sostenibilita-2024.pdf", texts)
    assert c["shortName"] == "Fonderie Ariotti" and c["name"] == "Fonderie Ariotti SpA"
    assert c["confidence"] == "high" and c["source"] == "content+url"


def test_parent_beats_subsidiaries_and_file_name_agrees():
    texts = ["Castings PLC annual report. " * 5, "Our subsidiary William Lee Ltd and Wm. Lee Ltd and Castings Ductile Ltd."]
    c = detect_company("https://castings.plc.uk/media/q4fdrmg3/castings-plc-sustainability-report-2024.pdf", texts)
    assert c["name"] == "Castings PLC" and c["confidence"] == "high"
    assert len({x["name"] for x in c["candidates"]}) == len(c["candidates"])  # no duplicates


def test_spelling_from_text_when_no_legal_form():
    c = detect_company("https://georgfischer.com/a.pdf", ["Welcome to Georg Fischer. Georg Fischer is a leader."])
    assert c["shortName"] == "Georg Fischer" and c["confidence"] == "high"


def test_only_the_url_is_low_confidence():
    c = detect_company("https://waupacafoundry.com/a.pdf", ["nothing helpful here"])
    assert c["name"] == "Waupacafoundry" and c["source"] == "url" and c["confidence"] == "low"


def test_file_name_used_when_text_is_silent():
    c = detect_company("https://cdn.example.net/files/acme-industries-annual-report-2024.pdf", ["nothing"])
    assert c["name"] == "Acme Industries" and c["source"] == "file name"


def test_content_name_unrelated_to_url_is_medium_when_repeated():
    c = detect_company("https://host.example.org/a.pdf", ["Zeta Metals Ltd " * 4])
    assert c["name"] == "Zeta Metals Ltd" and c["confidence"] == "medium"


def test_nothing_to_go_on():
    assert detect_company(None, [""])["name"] is None


def test_certificate_company_comes_from_the_certificate(tmp_path):
    from test_extract import TUV, make_pdf

    path = make_pdf(tmp_path / "c.pdf", TUV)
    with mock.patch("service.download", return_value=(path, {"finalUrl": "x"})):
        r = service.process("https://certs.example.com/acme.pdf", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert r["document"]["company"] == {"name": "Acme Castings GmbH", "shortName": None, "source": "certificate",
                                        "confidence": "high", "candidates": []}


def test_hyphenated_domain_is_respelled_from_the_text():
    texts = ["ESG REPORT 2024", "ABOUT BORG Automotive Group. BORG Automotive Group is headquartered in Denmark."]
    c = detect_company("https://borgautomotive-group.com/media/e5smim2i/esg-report-2024.pdf", texts)
    assert c["name"] == "BORG Automotive Group" and c["confidence"] == "high"
