#!/usr/bin/env python3
"""Extract metadata from PDF reports and certificates and write JSON, Excel and Markdown files.

    pip install -r requirements-extract.txt

    python extract_metadata.py path/to/pdf_folder                 # every PDF in the folder
    python extract_metadata.py path/to/folder -r                 # ... including sub-folders
    python extract_metadata.py report.pdf other.pdf              # specific files
    python extract_metadata.py --urls urls.txt                   # URLs, one per line
    python extract_metadata.py pdf_folder --urls urls.txt -o results/metadata

Writes <out>.json, <out>.xlsx and <out>.md (default <out> is "metadata"). One row per PDF:
company name, country, city, author or issuer, title of report, reporting period, start date, end date, notes.
Start and end dates are filled only when the report states them; nothing is inferred.
A PDF that cannot be read does not stop the run: it gets status "not read" and the reason in its notes.
"""
import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from analyze import analyze_pdf, process
from summary import summarize

FIELDS = [("companyName", "Company name"), ("country", "Country"), ("city", "City"),
          ("authorOrIssuer", "Author or issuer"), ("authorOrIssuerRole", "Author / issuer"),
          ("reportTitle", "Title of report"), ("reportingPeriod", "Reporting period"),
          ("startDate", "Start date"), ("endDate", "End date")]
FONT = "Arial"


def is_url(text: str) -> bool:
    return text.lower().startswith(("http://", "https://"))


def gather(sources: list[str], urls_file: str | None, recursive: bool) -> list[tuple[str, str]]:
    """Turn the command line into a list of ("file" | "url", value)."""
    items: list[tuple[str, str]] = []
    for source in sources:
        if is_url(source):
            items.append(("url", source))
            continue
        path = Path(source).expanduser()
        if path.is_dir():
            found = sorted(path.rglob("*") if recursive else path.glob("*"))
            items += [("file", str(p)) for p in found if p.is_file() and p.suffix.lower() == ".pdf"]
        elif path.is_file():
            items.append(("file", str(path)))
        else:
            sys.exit(f"Not found: {source}")
    if urls_file:
        for line in Path(urls_file).expanduser().read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                items.append(("url", line.strip()))
    return items


def extract_one(kind: str, value: str) -> dict:
    entry = {"url": value if kind == "url" else None, "file": value if kind == "file" else None}
    try:
        result = process(value) if kind == "url" else analyze_pdf(value)
        return {**entry, "status": "read", **summarize(result)}
    except Exception as error:  # one bad PDF must not stop the other 26
        return {**entry, "status": "not read", **{k: None for k, _ in FIELDS}, "notes": [str(error) or error.__class__.__name__]}


def _md(value) -> str:
    return "—" if value in (None, "", []) else str(value).replace("|", "\\|").replace("\n", " ")


def to_markdown(entries: list[dict]) -> str:
    read = sum(e["status"] == "read" for e in entries)
    out = ["# Report metadata", "",
           f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `extract_metadata.py`. {read} of {len(entries)} PDFs were read.", "",
           "| # | Company name | Country | City | Author or issuer | Title of report | Reporting period | Start date | End date |",
           "|---|---|---|---|---|---|---|---|---|"]
    for i, e in enumerate(entries, 1):
        who = f"{e['authorOrIssuer']} ({e['authorOrIssuerRole']})" if e["authorOrIssuer"] else None
        out.append("| " + " | ".join([str(i), _md(e["companyName"]), _md(e["country"]), _md(e["city"]), _md(who),
                                       _md(e["reportTitle"]), _md(e["reportingPeriod"]), _md(e["startDate"]), _md(e["endDate"])]) + " |")
    out += ["", "## Sources and notes", ""]
    for i, e in enumerate(entries, 1):
        out.append(f"{i}. `{e['url'] or e['file']}`")
        for note in e["notes"]:
            out.append(f"   - {note}")
    out += ["", "Reporting period is the period as written in the report. Start and end dates are given only when the report states them; "
                "an empty date means it is not stated. A note explains anything missing."]
    return "\n".join(out) + "\n"


def to_xlsx(entries: list[dict], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Metadata"
    header = ["#", "URL", "File", "Status"] + [label for _, label in FIELDS] + ["Notes"]
    ws.append(header)
    for i, e in enumerate(entries, 1):
        row = [i, e["url"], e["file"], e["status"]]
        for key, _ in FIELDS:
            value = e[key]
            row.append(date.fromisoformat(value) if key in ("startDate", "endDate") and value else value)
        row.append("; ".join(e["notes"]) or None)
        ws.append(row)
    col = {name: i for i, name in enumerate(header, 1)}
    widths = {"#": 5, "URL": 45, "File": 40, "Status": 10, "Company name": 28, "Country": 16, "City": 16, "Author or issuer": 28,
              "Author / issuer": 11, "Title of report": 38, "Reporting period": 26, "Start date": 12, "End date": 12, "Notes": 60}
    wrap = {col[n] for n in ("URL", "File", "Company name", "Title of report", "Reporting period", "Notes")}
    for cell in ws[1]:
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name=FONT, size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column in wrap)
            if cell.column in (col["Start date"], col["End date"]) and cell.value:
                cell.number_format = "yyyy-mm-dd"
    for name, i in col.items():
        ws.column_dimensions[get_column_letter(i)].width = widths[name]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    status = get_column_letter(col["Status"])
    notes = wb.create_sheet("Notes")
    for label, value in [
        ("Generated", f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by extract_metadata.py"),
        ("PDFs listed", "=COUNT(Metadata!A2:A2000)"),
        ("PDFs read", f'=COUNTIF(Metadata!{status}2:{status}2000,"read")'),
        ("PDFs not read", f'=COUNTIF(Metadata!{status}2:{status}2000,"not read")'),
        ("Author / issuer", "'author' = the author named in the PDF; 'issuer' = the company (or, for certificates, the certification body) that published it."),
        ("Reporting period", "The period as written in the report (for example 'April 1, 2024 - March 31, 2025' or 'FY2023'). Empty if the report does not state one."),
        ("Start / end date", "Filled only when the report states them. Nothing is inferred: an empty date means the report does not state it (a report that gives only a year end has an end date and no start date)."),
        ("Country / city", "The company's base, from an address block or a 'headquartered in' sentence in the report; the web address or VAT prefix is used only as a fallback and is noted."),
        ("Notes column", "Empty means every value was read directly from the report. A note flags anything uncertain or missing."),
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


def main(argv: list[str] | None = None) -> int:
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)  # damaged PDFs would otherwise spam the console
    ap = argparse.ArgumentParser(description="Extract metadata from PDF reports/certificates into JSON, Excel and Markdown.")
    ap.add_argument("sources", nargs="*", help="PDF files, folders of PDFs, or http(s) URLs")
    ap.add_argument("--urls", metavar="FILE", help="text file with one URL per line (# starts a comment)")
    ap.add_argument("-o", "--out", default="metadata", metavar="BASE", help="output path without extension (default: metadata)")
    ap.add_argument("-r", "--recursive", action="store_true", help="also look in sub-folders of a folder")
    args = ap.parse_args(argv)

    items = gather(args.sources, args.urls, args.recursive)
    if not items:
        ap.error("nothing to do: give PDF files, a folder, URLs, or --urls FILE")
    entries = []
    for n, (kind, value) in enumerate(items, 1):
        entry = extract_one(kind, value)
        entries.append(entry)
        label = Path(value).name if kind == "file" else value
        print(f"[{n}/{len(items)}] {entry['status']:8} {label[:70]}" + (f"  ->  {entry['companyName']}" if entry["companyName"] else ""), flush=True)

    base = Path(args.out)
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".json").write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    to_xlsx(entries, base.with_suffix(".xlsx"))
    base.with_suffix(".md").write_text(to_markdown(entries), encoding="utf-8")
    read = sum(e["status"] == "read" for e in entries)
    print(f"\n{read} of {len(entries)} read. Wrote {base.with_suffix('.json')}, {base.with_suffix('.xlsx')}, {base.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
