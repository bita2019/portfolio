"""Generic PDF metadata for documents that are not certificates (annual / sustainability reports)."""
import hashlib
import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from company import detect_company
from dates import report_dates
from location import detect_location

MAX_SCAN_PAGES = int(__import__("os").getenv("MAX_SCAN_PAGES", "300"))

FRAMEWORKS = {
    "ESRS": r"\bESRS\b",
    "CSRD": r"\bCSRD\b",
    "GRI": r"\bGRI\b",
    "TCFD": r"\bTCFD\b",
    "TNFD": r"\bTNFD\b",
    "SASB": r"\bSASB\b",
    "ISSB": r"\bISSB\b",
    "SBTi": r"\bSBTi\b",
    "CDP": r"\bCDP\b",
    "EU Taxonomy": r"EU Taxonomy",
    "GHG Protocol": r"GHG Protocol",
    "UN Global Compact": r"Global Compact",
}


SCOPE_HEADING = re.compile(
    r"(report parameters|about (?:this|the) (?:report|sustainability report|statement)|scope of (?:this|the) (?:report|statement)"
    r"|reporting (?:scope|boundar(?:y|ies))|basis (?:of|for) (?:the )?(?:preparation|reporting)|scope and boundar(?:y|ies))",
    re.I,
)
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_ANY_DATE = rf"(?:{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+{_MONTH}\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})"
# the first date may omit its year: "1 January to 31 December 2024"
PERIOD_RANGE = re.compile(
    rf"(?:{_ANY_DATE}|\d{{1,2}}\s+{_MONTH}|{_MONTH}\s+\d{{1,2}})\s*(?:-|\u2013|\u2014|to|until|through)\s*{_ANY_DATE}", re.I
)
PERIOD_YEAR = re.compile(r"\b(?:(?:calendar|financial|fiscal) year (?:ended? )?\d{4}|FY\s?\d{2,4})\b", re.I)
APPROACH = re.compile(
    r"\b(in accordance with|with reference to|based on|aligned with)\s+(?:the\s+)?(GRI|ESRS|TCFD|SASB|ISSB|CDP|GHG Protocol)\b", re.I
)


def _unbreak(text: str) -> str:
    """Rejoin words split across lines by hyphenation ("De - cember" -> "December")."""
    return re.sub(r"(?<=[A-Za-z]) - (?=[a-z])", "", " ".join(text.split()))


def _scope_statement(pages: list[str]) -> dict | None:
    """The report's own description of what it covers, taken from a heading line such as "Report Parameters"."""
    heading_line = re.compile(rf"^(?:{SCOPE_HEADING.pattern})(?:\s+and\s+[\w ]{{1,30}})?\s*$", re.I)
    for number, page in enumerate(pages, 1):
        lines = [l.strip() for l in page.splitlines()]
        for i, line in enumerate(lines):
            if not heading_line.match(line):
                continue
            rest = [l for l in lines[i + 1:] if l]
            if rest and len(rest[0]) < 30 and rest[0].lower().startswith("and "):
                rest = rest[1:]  # second line of a wrapped heading ("... and GRI Index")
            body = _unbreak(" ".join(rest))
            page_numbers = sum(bool(re.search(r"\s\d{1,3}$", l)) for l in rest[:12])
            if re.search(r"\.{4,}|(?:\. ){4,}", body[:260]) or page_numbers >= 4:
                continue  # a table of contents (dotted leaders / lines ending in page numbers), not the section itself
            if len(body) < 80:
                continue
            cut = body[:500]
            end = cut.rfind(". ")
            return {"heading": line, "text": (cut[: end + 1] if end > 120 else cut).strip(), "page": number}
    return None


def _scope(pages: list[str]) -> dict:
    full = "\n".join(pages)
    statement = _scope_statement(pages)
    period = None
    haystacks = ([statement["text"]] if statement else []) + [_unbreak(full)]
    for hay in haystacks:
        m = PERIOD_RANGE.search(hay) or PERIOD_YEAR.search(hay)
        if m:
            period = " ".join(m.group(0).split())
            break
    approach, seen = [], set()
    for m in APPROACH.finditer(full):
        item = (m.group(2).upper() if m.group(2).lower() != "ghg protocol" else "GHG Protocol", m.group(1).lower())
        if item not in seen:
            seen.add(item)
            approach.append({"framework": item[0], "basis": item[1]})
    ghg = {f"scope{n}": len(re.findall(rf"Scope\s*{n}\b", full, re.I)) for n in (1, 2, 3)}
    return {
        "statement": statement,
        "reportingPeriod": period,
        "reportedAgainst": approach,
        "ghgScopeMentions": ghg if any(ghg.values()) else None,
    }


def _outline_titles(outline, depth=0, out=None, limit=80) -> list[str]:
    out = [] if out is None else out
    for item in outline:
        if len(out) >= limit or depth > 1:
            break
        if isinstance(item, list):
            _outline_titles(item, depth + 1, out, limit)
        else:
            title = getattr(item, "title", None)
            if title:
                out.append(("  " * depth + title.strip()).rstrip())
    return out


GENERIC_TITLE = re.compile(
    r"^(untitled\b.*|(new |word |pdf )?document\d*|(powerpoint )?presentation\d*|slide \d+|microsoft (word|powerpoint)\b.*"
    r"|.*\.(docx?|pptx?|indd|pdf|qxp))$",
    re.I,
)
GENERIC_BOOKMARK = re.compile(r"^(slide|page|bookmark)\s*\d+$", re.I)


def _page_heading(page) -> str | None:
    """The largest text on the page, e.g. the cover title (chunks of the same size are joined)."""
    chunks: list[tuple[float, str]] = []

    def visit(text, cm, tm, font_dict, font_size):
        text = " ".join(text.split())
        if len(text) > 1 and "\n" not in text.strip():
            scale = abs(tm[3]) * (abs(cm[3]) or 1)
            chunks.append((round(font_size * scale, 1), text))

    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        return None
    if not chunks:
        return None
    biggest = max(size for size, _ in chunks)
    heading = " ".join(text for size, text in chunks if size >= biggest * 0.95)
    return " ".join(heading.split())[:160] or None


def _choose_title(pdf_title: str | None, heading: str | None, first_line: str | None) -> tuple[str | None, str | None]:
    """Prefer a meaningful PDF title, then the cover heading, then the first line of text."""
    if pdf_title and len(pdf_title.split()) >= 2 and not GENERIC_TITLE.match(pdf_title.strip()):
        return pdf_title.strip(), "pdf-metadata"
    if heading:
        return heading, "first-page-heading"
    if first_line:
        return first_line, "first-line"
    return None, None


def extract_document(path: str | Path, url: str | None = None) -> dict:
    path = Path(path)
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("The PDF is password protected.")
    meta = reader.metadata
    pages = reader.pages

    texts = []
    for page in list(pages)[:MAX_SCAN_PAGES]:
        try:
            texts.append(page.extract_text() or "")
        except Exception:  # a single unreadable page should not fail the whole document
            texts.append("")
    first = "\n".join(texts[:2])
    body = "\n".join(texts)

    first_line = next((l.strip() for l in first.splitlines() if len(l.strip()) > 3), None)
    year = re.search(r"(?<!\d)(20[12]\d)(?!\d)", f"{meta.title if meta else ''} {first}")

    frameworks = {name: n for name, rx in FRAMEWORKS.items() if (n := len(re.findall(rx, body)))}
    iso = sorted(set(re.sub(r"\s+", " ", m) for m in re.findall(r"ISO\s?\d{4,5}(?::\d{4})?", body)))

    try:
        outline = _outline_titles(reader.outline)
    except Exception:
        outline = []
    if outline and sum(bool(GENERIC_BOOKMARK.match(t.strip())) for t in outline) > len(outline) / 2:
        outline = []  # "Slide 1, Slide 2 ..." says nothing about the content

    created: datetime | None = None
    try:
        created = meta.creation_date if meta else None
    except Exception:
        pass

    pdf_title = (meta.title if meta and meta.title else None) or None
    title, title_source = _choose_title(pdf_title, _page_heading(pages[0]) if len(pages) else None, first_line)

    company = detect_company(url, texts)
    scope = _scope(texts)

    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "company": company,
        "location": detect_location(url, texts, company["name"], company["shortName"]),
        "dates": report_dates(texts, (scope["statement"] or {}).get("text")),
        "scope": scope,
        "title": title,
        "titleSource": title_source,
        "pdfTitle": pdf_title,
        "author": (meta.author if meta else None) or None,
        "creator": (meta.creator if meta else None) or None,
        "createdAt": created,
        "pages": len(pages),
        "pagesScanned": len(texts),
        "reportingYear": int(year.group(1)) if year else None,
        "outline": outline,
        "frameworks": dict(sorted(frameworks.items(), key=lambda kv: -kv[1])),
        "isoStandards": iso,
        "firstPageText": first.strip()[:1500],
    }
