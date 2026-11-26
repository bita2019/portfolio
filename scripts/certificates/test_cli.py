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
    assert set(entries[1]) == {"url", "requestedUrl", "file", "status", "companyName", "country", "city", "authorOrIssuer", "authorOrIssuerRole",
                               "reportTitle", "reportingPeriod", "startDate", "endDate", "notes"}
    assert entries[1]["companyName"] == "Acme Castings GmbH" and entries[1]["endDate"] == "2027-05-21"
    assert entries[2]["companyName"] == "BORG Automotive Group" and entries[2]["reportTitle"] == "ESG REPORT 2024"
    assert entries[0]["notes"] and entries[0]["companyName"] is None  # the reason, and no stop

    ws = load_workbook(out.with_suffix(".xlsx"))["Metadata"]
    assert [c.value for c in ws[1]][:7] == ["#", "URL", "Requested URL (if the link failed)", "File", "Status", "Company name", "Country"]
    assert ws.max_row == 4
    assert "2 of 3 PDFs were read" in out.with_suffix(".md").read_text()

    assert cli.main([str(pdfs), "-r", "-o", str(out)]) == 0  # sub-folders too
    assert len(json.loads(out.with_suffix(".json").read_text())) == 4


def test_gather_reads_urls_files_and_comments(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("# comment\nhttps://a.example/x.pdf\n\n  https://b.example/y.pdf  \n")
    pdf = make_pdf(tmp_path / "one.pdf", TUV)
    items = cli.gather([str(pdf), "https://c.example/z.pdf"], str(f), False)
    assert items == [("file", str(pdf), None), ("url", "https://c.example/z.pdf", None), ("url", "https://a.example/x.pdf", None), ("url", "https://b.example/y.pdf", None)]


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


def test_mongo_documents_follow_the_data_contract(tmp_path):
    import mongomock

    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    make_pdf(pdfs / "cert.pdf", TUV)
    (pdfs / "broken.pdf").write_text("not a pdf")
    entries = [cli.extract_one("file", str(p)) for p in sorted(pdfs.glob("*.pdf"))]
    entries.append({**entries[1], "url": "https://example.com/report.pdf", "file": None})  # a URL entry, same record

    collection = mongomock.MongoClient()["reports"]["report_metadata"]
    first = cli.write_mongo(entries, collection)
    assert first == {"written": 2, "inserted": 2, "updated": 0, "skipped": 1}  # the broken PDF is not written
    docs = {d["url"]: d for d in collection.find({}, {"_id": 0})}
    assert set(docs) == {(pdfs / "cert.pdf").resolve().as_uri(), "https://example.com/report.pdf"}
    doc = docs["https://example.com/report.pdf"]
    assert list(doc) == cli.CONTRACT_KEYS  # exactly the agreed keys, in order
    assert doc["companyName"] == "Acme Castings GmbH" and doc["startDate"] == "2024-05-22" and doc["endDate"] == "2027-05-21"
    assert isinstance(doc["startDate"], str)

    again = cli.write_mongo(entries, collection)  # running it again must not duplicate
    assert collection.count_documents({}) == 2 and again["inserted"] == 0


def test_cli_writes_the_contract_file_and_reads_a_file_or_a_url_list(tmp_path):
    pdf = make_pdf(tmp_path / "one.pdf", TUV)
    out = tmp_path / "out" / "m"
    assert cli.main([str(pdf), "-o", str(out)]) == 0
    contract = json.loads(out.with_suffix(".mongo.json").read_text())
    assert [list(d) for d in contract] == [cli.CONTRACT_KEYS] and contract[0]["url"] == pdf.resolve().as_uri()


def test_mongo_flag_without_a_connection_string_is_an_error(tmp_path, monkeypatch):
    import pytest

    monkeypatch.delenv("MONGODB_URI", raising=False)
    with pytest.raises(SystemExit):
        cli.main([str(make_pdf(tmp_path / "x.pdf", TUV)), "--mongo"])


def test_a_downloaded_pdf_replaces_the_fetch_of_its_url_in_the_same_position(tmp_path):
    urls = tmp_path / "urls.txt"
    urls.write_text("https://a.example/one.pdf\nhttps://blocked.example/report.pdf\nhttps://c.example/three.pdf\n")
    pdf = make_pdf(tmp_path / "saved.pdf", TUV)
    items = cli.gather([], str(urls), False, {str(pdf): "https://blocked.example/report.pdf"})
    assert [(k, h) for k, v, h in items] == [("url", None), ("file", "https://blocked.example/report.pdf"), ("url", None)]
    entry = cli.extract_one("file", str(pdf), "https://blocked.example/report.pdf")
    assert entry["url"] == "https://blocked.example/report.pdf" and entry["file"] == str(pdf) and entry["status"] == "read"
    assert entry["notes"][0].startswith("read from the PDF file supplied")
    assert cli.to_contract(entry)["url"] == "https://blocked.example/report.pdf"  # the contract keeps the published address


def test_file_url_option_rejects_a_bad_pair(tmp_path):
    import pytest

    with pytest.raises(SystemExit):
        cli.main([str(make_pdf(tmp_path / "x.pdf", TUV)), "--file-url", "missing.pdf=https://x.example/a.pdf"])


def test_cli_leaves_the_start_empty_for_a_year_end_unless_asked_to_derive_it(tmp_path):
    from test_extract import make_pdf as mk

    pdf = mk(tmp_path / "ye.pdf", ["ESG Report 2023", "This report covers the year ended 31 December 2023.", "Acme Ltd reported results."])
    plain = cli.extract_one("file", str(pdf))
    assert (plain["startDate"], plain["endDate"]) == (None, "2023-12-31")
    derived = cli.extract_one("file", str(pdf), derive_start=True)
    assert (derived["startDate"], derived["endDate"]) == ("2023-01-01", "2023-12-31")
    out = tmp_path / "o"
    assert cli.main([str(pdf), "-o", str(out)]) == 0 and cli.main([str(pdf), "--derive-year-start", "-o", str(tmp_path / "d")]) == 0
    assert json.loads(out.with_suffix(".json").read_text())[0]["startDate"] is None
    assert json.loads((tmp_path / "d.json").read_text())[0]["startDate"] == "2023-01-01"
