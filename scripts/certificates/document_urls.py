#!/usr/bin/env python3
"""Pair every URL with its extracted metadata and write a JSON file plus a Markdown document.

    python document_urls.py examples/urls.txt examples/url-metadata
    -> examples/url-metadata.json, examples/url-metadata.md
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

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


if __name__ == "__main__":
    src, base = sys.argv[1], Path(sys.argv[2])
    urls = [l.strip() for l in Path(src).read_text().splitlines() if l.strip() and not l.startswith("#")]
    entries = collect(urls)
    base.with_suffix(".json").write_text(json.dumps(entries, indent=2, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o), ensure_ascii=False), encoding="utf-8")
    base.with_suffix(".md").write_text(to_markdown(entries), encoding="utf-8")
    for e in entries:
        print(e["status"], e["url"][:90])
