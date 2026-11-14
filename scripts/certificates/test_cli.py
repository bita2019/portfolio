import json

import pymupdf
from openpyxl import load_workbook

import extract_metadata as cli
from company import detect_company
from test_extract import TUV, make_pdf


def _report(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), "ESG REPORT 2024", fontsize=40)
    page.insert_text((50, 200), "BORG Automotive Group reported a revenue of 5 million. BORG Automotive Group is based in Denmark.", fontsize=8)
    page.insert_text((50, 220), "BORG Automotive Group has moved. BORG Automotive Group employs staff.", fontsize=8)
    doc.save(path)


def test_folder_run_writes_json_xlsx_and_markdown(tmp_path, capsys):
    pdfs = tmp_path / "pdfs"
    (pdfs / "nested").mkdir(parents=True)
    make_pdf(pdfs / "cert.pdf", TUV)
    _report(pdfs / "report.pdf")
    (pdfs / "broken.pdf").write_text("not a pdf")
    make_pdf(pdfs / "nested" / "deep.pdf", TUV)
    (pdfs / "notes.txt").write_text("ignored")

    out = tmp_path / "out" / "result"
    assert cli.main([str(pdfs), "-o", str(out)]) == 0
    entries = json.loads(out.with_suffix(".json").read_text())
    assert [(e["file"].split("/")[-1], e["status"]) for e in entries] == [("broken.pdf", "not read"), ("cert.pdf", "read"), ("report.pdf", "read")]
    assert set(entries[1]) == {"url", "file", "status", "companyName", "country", "city", "authorOrIssuer", "authorOrIssuerRole",
                               "reportTitle", "reportingPeriod", "startDate", "endDate", "notes"}
    assert entries[1]["companyName"] == "Acme Castings GmbH" and entries[1]["endDate"] == "2027-05-21"
    assert entries[2]["companyName"] == "BORG Automotive Group" and entries[2]["reportTitle"] == "ESG REPORT 2024"
    assert entries[0]["notes"] and entries[0]["companyName"] is None  # the reason, and no stop

    ws = load_workbook(out.with_suffix(".xlsx"))["Metadata"]
    assert [c.value for c in ws[1]][:6] == ["#", "URL", "File", "Status", "Company name", "Country"]
    assert ws.max_row == 4
    assert "2 of 3 PDFs were read" in out.with_suffix(".md").read_text()

    assert cli.main([str(pdfs), "-r", "-o", str(out)]) == 0  # sub-folders too
    assert len(json.loads(out.with_suffix(".json").read_text())) == 4


def test_gather_reads_urls_files_and_comments(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("# comment\nhttps://a.example/x.pdf\n\n  https://b.example/y.pdf  \n")
    pdf = make_pdf(tmp_path / "one.pdf", TUV)
    items = cli.gather([str(pdf), "https://c.example/z.pdf"], str(f), False)
    assert items == [("file", str(pdf)), ("url", "https://c.example/z.pdf"), ("url", "https://a.example/x.pdf"), ("url", "https://b.example/y.pdf")]


def test_company_without_a_url_prefers_the_subject_over_headings_and_ignores_codes_auditors_and_abbreviations():
    text = ("Supply Chain Conflict Minerals Supply Chain. " * 20
            + "BORG Automotive Group reported a revenue. BORG Automotive Group is based in Denmark. BORG Automotive Group has grown. "
            + "Collection Bargaining AA Child Labor AB. PricewaterhouseCoopers AG audited it. WFI Inc. is an abbreviation.")
    c = detect_company(None, [text])
    assert c["name"] == "BORG Automotive Group" and c["source"] == "content"
    assert all("AA" not in x["name"] and "Pricewaterhouse" not in x["name"] and x["name"] != "WFI Inc" for x in c["candidates"])


def test_formal_legal_name_beats_a_frequent_division():
    text = "Flow Solutions grew. Flow Solutions is global. " * 10 + "Georg Fischer AG is headquartered in Switzerland. Georg Fischer AG, Schaffhausen. Georg Fischer AG."
    assert detect_company(None, [text])["name"] == "Georg Fischer AG"
