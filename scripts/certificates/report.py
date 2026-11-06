"""Generic PDF metadata for documents that are not certificates (annual / sustainability reports)."""
import hashlib
import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

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


def extract_document(path: str | Path) -> dict:
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

    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "title": (meta.title if meta and meta.title else None) or first_line,
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
