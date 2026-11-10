#!/usr/bin/env python3
"""Pair every URL with its extracted metadata and write a JSON file plus a Markdown document.

    python document_urls.py examples/urls.txt examples/url-metadata
    -> examples/url-metadata.json, examples/url-metadata.md, examples/url-metadata.xlsx
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from fetch import FetchError, url_metadata
from service import process


def collect(urls: list[str]) -> list[dict]:
    entries = []
    for url in urls:
        entry = {"url": url, "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            result = process(url)
            entry.update(status="ok", metadata=result)
        except FetchError as error:
            entry.update(status="failed", httpStatus=error.status, error=str(error),
                         metadata={"source": url_metadata(url)})  # what the URL alone tells us
        entries.append(entry)
    return entries


def _md(value) -> str:
    return "—" if value in (None, "", [], {}) else str(value).replace("|", "\\|").replace("\n", " ")


def _row(label: str, value) -> str:
    return f"| {label} | {_md(value)} |"


def to_markdown(entries: list[dict]) -> str:
    ok = sum(e["status"] == "ok" for e in entries)
    out = ["# Report URLs and their extracted metadata", "",
           f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `document_urls.py`. "
           f"{ok} of {len(entries)} URLs were downloaded and read; the rest are listed with what the URL alone reveals.", "",
           "| # | Company | Document | Year | Status |", "|---|---|---|---|---|"]
    for i, e in enumerate(entries, 1):
        m = e["metadata"]
        company = m["document"]["company"]["name"] if e["status"] == "ok" else None
        out.append(f"| {i} | {_md(company)} | {_md(m['source']['documentType'])} | {_md(m['source']['year'])} | "
                   f"{'✅ read' if e['status'] == 'ok' else '⚠️ ' + str(e['httpStatus'])} |")
    for i, e in enumerate(entries, 1):
        m, src = e["metadata"], e["metadata"]["source"]
        out += ["", f"## {i}. {src['host']}", "", f"`{e['url']}`", ""]
        if e["status"] != "ok":
            out += [f"**Not read.** {e['error']}", "", "From the URL alone:", "", "| Field | Value |", "|---|---|",
                    _row("Canonical URL", src["canonicalUrl"]), _row("Dropped tracking parameters", ", ".join(src["strippedParameters"])),
                    _row("Document type", src["documentType"]), _row("Year", src["year"]), _row("Language", src["language"])]
            continue
        d, c, v = m["document"], m["document"]["company"], m["validation"]
        out += ["| Field | Value |", "|---|---|",
                _row("Company", f"{c['name']} ({c['confidence']} confidence, from {c['source']})"),
                _row("Short name", c["shortName"]),
                _row("Title", f"{d['title']} (from {d['titleSource']})"),
                _row("Reporting year", d["reportingYear"]),
                _row("Date in file name", src.get("dateInName")),
                _row("Document type (from URL)", src["documentType"]),
                _row("Language (from URL)", src["language"]),
                _row("Canonical URL", src["canonicalUrl"]),
                _row("Dropped tracking parameters", ", ".join(src["strippedParameters"])),
                _row("Pages", d["pages"]),
                _row("File size", f"{src['bytes'] / 1e6:.1f} MB"),
                _row("Last modified (server)", src["lastModified"]),
                _row("PDF created", d["createdAt"]),
                _row("Created with", d["creator"]),
                _row("Author", d["author"]),
                _row("Scope statement", (lambda st: f"{st['text']} (p. {st['page']}, \"{st['heading']}\")" if st else "none found in the report")(d["scope"]["statement"])),
                _row("Reporting period", d["scope"]["reportingPeriod"] or "not stated"),
                _row("Reported against", ", ".join(f"{a['framework']} ({a['basis']})" for a in d["scope"]["reportedAgainst"]) or "not stated"),
                _row("GHG scope 1 / 2 / 3 mentions", " / ".join(str(d["scope"]["ghgScopeMentions"][k]) for k in ("scope1", "scope2", "scope3")) if d["scope"]["ghgScopeMentions"] else "none"),
                _row("Frameworks mentioned", ", ".join(f"{k} ×{n}" for k, n in d["frameworks"].items())),
                _row("ISO standards mentioned", ", ".join(d["isoStandards"])),
                _row("Outline", "; ".join(x.strip() for x in d["outline"][:10]) + (" …" if len(d["outline"]) > 10 else "")),
                _row("SHA-256", f"`{d['sha256']}`"),
                _row("Validation", ("passed" if v["passed"] else "failed") + " — " + ", ".join(
                    f"{x['check']}: {'ok' if x['ok'] else 'FAILED'}" for x in v["checks"]))]
        if len(c["candidates"]) > 1:
            out += ["", "Company candidates considered: " + "; ".join(
                f"{x['name']} ({x['source']})" for x in c["candidates"])]
    out += ["", "## Notes", "",
            "- *Scope* is what the report itself says it covers (a heading such as \"Report Parameters\" or \"About this report\"), so it is empty when the report has no such section. *GHG scope mentions* count the words \"Scope 1/2/3\" and say nothing about what was measured.",
            "- *Frameworks* counts are plain word matches, so \"GRI ×1\" means the word appears once, not that the report follows GRI.",
            "- *Company* confidence is high when the report text and the URL agree, medium when only the text names it (3+ mentions), low when only the URL does.",
            "- Re-run `python document_urls.py examples/urls.txt examples/url-metadata` after editing `examples/urls.txt`."]
    return "\n".join(out) + "\n"


FONT = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F3864")


def _cell(value):
    """Excel has no time zones or lists: dates become text, lists become one string."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) or None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return value


def _fields(e: dict) -> list[tuple[str, object]]:
    """Every metadata field of one URL as (field, value) pairs."""
    m, src = e["metadata"], e["metadata"]["source"]
    rows = [("Status", e["status"]), ("Fetched at", e["fetchedAt"]), ("Canonical URL", src["canonicalUrl"]),
            ("Dropped tracking parameters", src["strippedParameters"]), ("Document type (from URL)", src["documentType"]),
            ("Year (from URL)", src["year"]), ("Language (from URL)", src["language"]), ("Date in file name", src.get("dateInName"))]
    if e["status"] != "ok":
        return rows + [("Error", e["error"]), ("HTTP status returned by the service", e["httpStatus"])]
    d, c, v = m["document"], m["document"]["company"], m["validation"]
    sc = d["scope"]
    ghg = sc["ghgScopeMentions"]
    return rows + [
        ("Kind", m["kind"]), ("Company", c["name"]), ("Company short name", c["shortName"]),
        ("Company confidence", c["confidence"]), ("Company evidence", c["source"]),
        ("Title", d["title"]), ("Title source", d["titleSource"]), ("PDF metadata title", d["pdfTitle"]),
        ("Reporting year", d["reportingYear"]),
        ("Scope statement", sc["statement"]["text"] if sc["statement"] else None),
        ("Scope statement page", sc["statement"]["page"] if sc["statement"] else None),
        ("Reporting period", sc["reportingPeriod"]),
        ("Reported against", [f"{a['framework']} ({a['basis']})" for a in sc["reportedAgainst"]]),
        ("GHG Scope 1 mentions", ghg["scope1"] if ghg else None), ("GHG Scope 2 mentions", ghg["scope2"] if ghg else None),
        ("GHG Scope 3 mentions", ghg["scope3"] if ghg else None),
        ("Pages", d["pages"]), ("File size (MB)", round(src["bytes"] / 1e6, 2)), ("Content type", src["contentType"]),
        ("Last modified (server)", src["lastModified"]), ("PDF created", d["createdAt"]), ("Created with", d["creator"]),
        ("Author", d["author"]), ("Outline", d["outline"]),
        ("Frameworks mentioned", [f"{k} x{n}" for k, n in d["frameworks"].items()]),
        ("ISO standards mentioned", d["isoStandards"]), ("SHA-256", d["sha256"]),
        ("Validation passed", v["passed"]),
        ("Validation checks", [f"{x['check']}: {'ok' if x['ok'] else 'FAILED'}" for x in v["checks"]]),
    ]


def _sheet(wb, title, header, rows, widths, wrap_cols=()):
    ws = wb.create_sheet(title)
    ws.append(header)
    for row in rows:
        ws.append([_cell(x) for x in row])
    for cell in ws[1]:
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name=FONT, size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column in wrap_cols)
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def to_xlsx(entries: list[dict], path: Path) -> None:
    wb = Workbook()
    wb.remove(wb.active)

    summary = []
    for i, e in enumerate(entries, 1):
        f = dict(_fields(e))
        ok = e["status"] == "ok"
        summary.append([i, e["url"], "read" if ok else "not read", f.get("Company"), f.get("Company confidence"),
                        f.get("Title"), f.get("Reporting year") or f["Year (from URL)"], f["Document type (from URL)"],
                        f.get("Pages"), f.get("File size (MB)"), f.get("Reporting period"), f.get("Reported against"),
                        f.get("GHG Scope 1 mentions"), f.get("GHG Scope 2 mentions"), f.get("GHG Scope 3 mentions"),
                        None if ok else f["Error"]])
    _sheet(wb, "Summary",
           ["#", "URL", "Status", "Company", "Company confidence", "Title", "Year", "Document type", "Pages", "Size (MB)",
            "Reporting period", "Reported against", "GHG Scope 1 mentions", "GHG Scope 2 mentions", "GHG Scope 3 mentions", "Why not read"],
           summary, [5, 60, 10, 28, 12, 34, 7, 34, 7, 9, 28, 24, 11, 11, 11, 50], wrap_cols={2, 4, 6, 8, 11, 12, 16})

    long = [[i, e["url"], label, value] for i, e in enumerate(entries, 1) for label, value in _fields(e)]
    _sheet(wb, "Details", ["#", "URL", "Field", "Value"], long, [5, 50, 32, 90], wrap_cols={2, 4})

    cands = [[i, e["url"], c["name"], c["shortName"], c["source"], c["mentions"]]
             for i, e in enumerate(entries, 1) if e["status"] == "ok"
             for c in e["metadata"]["document"]["company"]["candidates"]]
    _sheet(wb, "Company candidates", ["#", "URL", "Candidate", "Short name", "Evidence", "Mentions"], cands,
           [5, 50, 36, 28, 14, 10], wrap_cols={2})

    notes = wb.create_sheet("Notes")
    lines = [
        ("Generated", f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by document_urls.py (re-run it after editing examples/urls.txt)"),
        ("URLs listed", "=COUNTA(Summary!B2:B200)"),
        ("URLs read", '=COUNTIF(Summary!C2:C200,"read")'),
        ("URLs not read", '=COUNTIF(Summary!C2:C200,"not read")'),
        ("Summary sheet", "One row per URL with the main fields. Use the filter arrows to sort or filter."),
        ("Details sheet", "Every metadata field of every URL, one row per field - filter by URL or by Field."),
        ("Company candidates sheet", "Every company name the extractor considered, with the evidence for it."),
        ("Company confidence", "high = report text and URL agree; medium = only the text names it (3+ mentions); low = only the URL does."),
        ("Scope", "What the report itself says it covers (a heading such as 'Report Parameters'). Blank means the report has no such section."),
        ("GHG Scope mentions", "Counts of the words 'Scope 1/2/3'. They say nothing about what was measured."),
        ("Frameworks mentioned", "Plain word counts: 'GRI x1' means the word appears once, not that the report follows GRI."),
        ("Not read", "The URL did not return a PDF, or the sandbox/network blocked the host. See 'Why not read' on the Summary sheet."),
    ]
    for label, value in lines:
        notes.append([label, value])
    for row in notes.iter_rows():
        row[0].font = Font(name=FONT, bold=True, size=10)
        row[1].font = Font(name=FONT, size=10)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        row[0].alignment = Alignment(vertical="top")
    notes.column_dimensions["A"].width = 26
    notes.column_dimensions["B"].width = 110
    wb.move_sheet("Notes", offset=0)
    wb.save(path)


if __name__ == "__main__":
    src, base = sys.argv[1], Path(sys.argv[2])
    urls = [l.strip() for l in Path(src).read_text().splitlines() if l.strip() and not l.startswith("#")]
    entries = collect(urls)
    base.with_suffix(".json").write_text(json.dumps(entries, indent=2, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o), ensure_ascii=False), encoding="utf-8")
    base.with_suffix(".md").write_text(to_markdown(entries), encoding="utf-8")
    to_xlsx(entries, base.with_suffix(".xlsx"))
    for e in entries:
        print(e["status"], e["url"][:90])
