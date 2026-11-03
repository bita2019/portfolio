"""Run: pytest scripts/certificates   (set SAMPLE_CERT_PDF to also test a real certificate)"""
import os
from pathlib import Path

import pymupdf
import pytest

from extract import embedding_text, extract_certificate


def make_pdf(path: Path, lines: list[str]) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for line in lines:
        page.insert_text((60, y), line, fontsize=11)
        y += 18
    doc.save(path)
    return path


TUV = [
    "CERTIFICATE",
    "Certificate Registration No.: 12 100 9650 TMS / Order No.: 70006345",
    "The Certification Body",
    "of TUV SUD Management Service GmbH",
    "certifies that the organization",
    "Acme Castings GmbH",
    "Hauptstrasse 1",
    "Building B",
    "35260 Stadtallendorf",
    "Germany",
    "for the scope",
    "Design and manufacturing of",
    "iron castings",
    "has established and applies a Quality Management System.",
    "requirements according to",
    "DIN EN ISO 9001:2015",
    "are fulfilled.",
    "The certificate is valid from 2024-05-22 until 2027-05-21.",
    "Fred Wenke",
    "Head of Certification Body",
    "Munich, 2024-05-29",
]


def test_standard_layout(tmp_path):
    c = extract_certificate(make_pdf(tmp_path / "a.pdf", TUV))
    assert c["registrationNo"] == "12 100 9650 TMS"
    assert c["orderNo"] == "70006345"
    assert c["organization"] == {
        "name": "Acme Castings GmbH",
        "street": "Hauptstrasse 1, Building B",
        "postalCode": "35260",
        "city": "Stadtallendorf",
        "country": "Germany",
    }
    assert c["scope"] == "Design and manufacturing of iron castings"
    assert c["standard"] == "DIN EN ISO 9001:2015"
    assert (c["validFrom"].date().isoformat(), c["validUntil"].date().isoformat()) == ("2024-05-22", "2027-05-21")
    assert c["issuedPlace"] == "Munich" and c["issuedDate"].date().isoformat() == "2024-05-29"
    assert c["signedBy"] == "Fred Wenke"
    assert c["pdf"]["pages"] == 1 and len(c["sha256"]) == 64


@pytest.mark.parametrize("std", ["ISO 14001:2015", "IATF 16949:2016", "ISO 45001:2018"])
def test_other_standards(tmp_path, std):
    lines = [std if l.startswith("DIN EN") else l for l in TUV]
    assert extract_certificate(make_pdf(tmp_path / "b.pdf", lines))["standard"] == std


def test_non_certificate_does_not_crash(tmp_path):
    c = extract_certificate(make_pdf(tmp_path / "c.pdf", ["Sustainability report 2024", "We cut emissions by 20%."]))
    assert c["organization"]["name"] is None and c["scope"] is None and c["standard"] is None
    assert c["validUntil"] is None
    assert embedding_text(c) == ""  # nothing to embed, but no exception


def test_blank_pdf(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    doc.save(tmp_path / "blank.pdf")
    assert extract_certificate(tmp_path / "blank.pdf")["scope"] is None


def test_same_file_same_hash(tmp_path):
    p = make_pdf(tmp_path / "d.pdf", TUV)
    assert extract_certificate(p)["sha256"] == extract_certificate(p)["sha256"]


@pytest.mark.skipif(not os.getenv("SAMPLE_CERT_PDF"), reason="no real sample provided")
def test_real_sample():
    c = extract_certificate(os.environ["SAMPLE_CERT_PDF"])
    assert c["organization"]["name"] == "Fritz Winter Eisengießerei GmbH & Co. KG"
    assert c["standard"] == "DIN EN ISO 9001:2015"
    assert c["validUntil"].date().isoformat() == "2027-05-21"
    assert c["registrationNo"] == "12 100 9650 TMS"
