"""Generic PDF metadata for documents that are not certificates (annual / sustainability reports)."""
import hashlib
import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from company import detect_company

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


GENERIC_TITLE = re.compile(r"^(untitled|document\d*|microsoft (word|powerpoint)\b.*|.*\.(docx?|pptx?|indd|pdf|qxp))$", re.I)


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

    created: datetime | None = None
    try:
        created = meta.creation_date if meta else None
    except Exception:
        pass

    pdf_title = (meta.title if meta and meta.title else None) or None
    title, title_source = _choose_title(pdf_title, _page_heading(pages[0]) if len(pages) else None, first_line)

    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "company": detect_company(url, texts),
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
