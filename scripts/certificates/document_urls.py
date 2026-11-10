#!/usr/bin/env python3
"""Run a list of URLs through the extractor and write the short metadata record as JSON, Markdown and Excel.

    python document_urls.py examples/urls.txt examples/url-metadata
    -> examples/url-metadata.json, examples/url-metadata.md, examples/url-metadata.xlsx

Each row has: company name, country, city, author or issuer, report title, start date, end date (plus notes).
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from fetch import FetchError
from service import process
from summary import summarize

FIELDS = [("companyName", "Company name"), ("country", "Country"), ("city", "City"),
          ("authorOrIssuer", "Author or issuer"), ("authorOrIssuerRole", "Author / issuer"),
          ("reportTitle", "Title of report"), ("startDate", "Start date"), ("endDate", "End date")]
FONT = "Arial"


def collect(urls: list[str]) -> list[dict]:
    entries = []
    for url in urls:
        try:
            entries.append({"url": url, "status": "read", **summarize(process(url))})
        except FetchError as error:
            entries.append({"url": url, "status": "not read", **{k: None for k, _ in FIELDS}, "notes": [str(error)]})
    return entries


def _md(value) -> str:
    return "—" if value in (None, "", []) else str(value).replace("|", "\\|").replace("\n", " ")


def to_markdown(entries: list[dict]) -> str:
    read = sum(e["status"] == "read" for e in entries)
    out = ["# Report URLs and their metadata", "",
           f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `document_urls.py`. {read} of {len(entries)} URLs were read.", "",
           "| # | Company name | Country | City | Author or issuer | Title of report | Start date | End date |",
           "|---|---|---|---|---|---|---|---|"]
    for i, e in enumerate(entries, 1):
        who = f"{e['authorOrIssuer']} ({e['authorOrIssuerRole']})" if e["authorOrIssuer"] else None
        out.append("| " + " | ".join([str(i), _md(e["companyName"]), _md(e["country"]), _md(e["city"]), _md(who),
                                       _md(e["reportTitle"]), _md(e["startDate"]), _md(e["endDate"])]) + " |")
    out += ["", "## URLs and notes", ""]
    for i, e in enumerate(entries, 1):
        out.append(f"{i}. `{e['url']}`")
        for note in e["notes"]:
            out.append(f"   - {note}")
    out += ["", "A note means the value was inferred or could not be found; a row without notes was read directly from the report."]
    return "\n".join(out) + "\n"


def to_xlsx(entries: list[dict], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Metadata"
    header = ["#", "URL", "Status"] + [label for _, label in FIELDS] + ["Notes"]
    ws.append(header)
    for i, e in enumerate(entries, 1):
        row = [i, e["url"], e["status"]]
        for key, _ in FIELDS:
            value = e[key]
            row.append(date.fromisoformat(value) if key in ("startDate", "endDate") and value else value)
        row.append("; ".join(e["notes"]) or None)
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name=FONT, size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column in (2, 4, 9, 12))
            if cell.column in (10, 11) and cell.value:
                cell.number_format = "yyyy-mm-dd"
    for i, width in enumerate([5, 55, 10, 28, 16, 16, 28, 11, 38, 12, 12, 60], 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    notes = wb.create_sheet("Notes")
    for label, value in [
        ("Generated", f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by document_urls.py (re-run it after editing examples/urls.txt)"),
        ("URLs listed", "=COUNTA(Metadata!B2:B200)"),
        ("URLs read", '=COUNTIF(Metadata!C2:C200,"read")'),
        ("URLs not read", '=COUNTIF(Metadata!C2:C200,"not read")'),
        ("Author / issuer", "'author' = the author named in the PDF; 'issuer' = the company (or, for certificates, the certification body) that published it."),
        ("Start / end date", "Taken from the report when it states its period. Where it does not, the date is inferred (assumed calendar year, or end date stated and start assumed 12 months earlier) and the Notes column says so."),
        ("Country / city", "The company's base, from an address block or a 'headquartered in' sentence in the report; the web address or VAT prefix is used only as a fallback and is noted."),
        ("Notes column", "Empty means every value was read directly from the report. A note flags anything inferred, uncertain or missing."),
    ]:
        notes.append([label, value])
    for row in notes.iter_rows():
        row[0].font = Font(name=FONT, bold=True, size=10)
        row[1].font = Font(name=FONT, size=10)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        row[0].alignment = Alignment(vertical="top")
    notes.column_dimensions["A"].width = 18
    notes.column_dimensions["B"].width = 110
    wb.save(path)


if __name__ == "__main__":
    src, base = sys.argv[1], Path(sys.argv[2])
    urls = [l.strip() for l in Path(src).read_text().splitlines() if l.strip() and not l.startswith("#")]
    entries = collect(urls)
    base.with_suffix(".json").write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    base.with_suffix(".md").write_text(to_markdown(entries), encoding="utf-8")
    to_xlsx(entries, base.with_suffix(".xlsx"))
    for e in entries:
        print(e["status"], e["url"][:90])
