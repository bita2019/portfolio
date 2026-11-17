"""Find a report on the company's own website when the link we were given does not work.

A link that fails (HTTP 403 / 404, a "page not found" page, a moved file) says nothing about whether the report exists.
So before giving up we look where a person would: the company's site, its sustainability / ESG / publications pages.
Candidate PDFs are scored by how well they match the original link (year, words) and each downloaded one is checked
to really be that report before it is accepted.
"""
import re
import tempfile
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from fetch import FetchError, download, fetch_page

MAX_PAGES = 24          # pages fetched while looking
MAX_DEPTH = 2           # links followed from the start pages
TRY_PDFS = 4            # best-scoring PDFs that are downloaded and checked
INTEREST = re.compile(r"sustainab|esg|report|publication|librar|document|download|csr|environment|climate|responsib|disclos|statement|"
                      r"investor|reporting", re.I)
REPORT_WORDS = re.compile(r"sustainab|esg|environmental[\s-]*report|data[\s-]*book|integrated[\s-]*report|csr|climate", re.I)
LESS_LIKELY = re.compile(r"polic|code[\s-]of|supplier|fact[\s-]?sheet|presentation|brochure|press|summary|assurance|gri[\s-]content|"
                         r"tcfd|index|questionnaire|slides|infographic|poster|flyer", re.I)
STOP = {"pdf", "web", "final", "fnl", "def", "www", "com", "assets", "media", "files", "file", "docs", "download", "interactive",
        "uuid", "asset", "the", "and", "en", "for", "of", "content", "dam", "upload", "uploads", "wp"}
SECOND_LEVEL = {"co", "com", "org", "net", "plc", "ltd", "ac", "gov", "edu"}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []
        elif tag in ("link", "iframe", "embed", "object"):
            href = dict(attrs).get("href") or dict(attrs).get("src") or dict(attrs).get("data")
            if href:
                self.links.append((href, ""))

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def extract_links(html: str, base: str) -> list[tuple[str, str]]:
    parser = _Links()
    try:
        parser.feed(html)
    except Exception:
        pass
    out = []
    for href, text in parser.links:
        href = href.strip()
        if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
            out.append((urljoin(base, href).split("#")[0], text))
    return out


def registrable_domain(host: str) -> str:
    labels = host.lower().split(".")
    if len(labels) <= 2 or re.fullmatch(r"[\d.]+", host):
        return host.lower()
    return ".".join(labels[-3:] if labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2 else labels[-2:])


def start_pages(url: str) -> list[str]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    domain = registrable_domain(host)
    hosts = [host]
    if domain != host or not re.fullmatch(r"[\d.]+", host):
        hosts += [f"www.{domain}", domain, f"corporate.{domain}"]
    seen = []
    for h in hosts:
        page = f"{parts.scheme}://{h}{':' + str(parts.port) if parts.port and h == host else ''}/"
        if page not in seen:
            seen.append(page)
    return seen


def hint_from(url: str) -> dict:
    path = unquote(urlsplit(url).path)
    stem = re.sub(r"\.pdf$", "", path.rsplit("/", 1)[-1], flags=re.I)
    year = re.search(r"(?<!\d)(20\d\d)(?!\d)", stem) or re.search(r"(?<!\d)(20\d\d)(?!\d)", path)
    tokens = {t for t in re.split(r"[^a-z0-9]+", stem.lower()) if len(t) > 2 and not t.isdigit() and t not in STOP}
    return {"year": int(year.group(1)) if year else None, "tokens": tokens}


def score_link(link: str, text: str, hint: dict) -> int:
    low = unquote(f"{link} {text}").lower()
    score = 0
    if hint["year"]:
        years = set(re.findall(r"(?<!\d)(20\d\d)(?!\d)", low))
        if str(hint["year"]) in years:
            score += 6
        elif years:
            score -= 6  # a different year's report
    score += 2 * sum(1 for t in hint["tokens"] if t in low)
    if REPORT_WORDS.search(low):
        score += 3
    if LESS_LIKELY.search(low):
        score -= 3
    if ".pdf" in low:
        score += 1
    return score


def is_pdf_link(link: str) -> bool:
    path = urlsplit(link).path.lower()
    return path.endswith(".pdf") or ".pdf?" in link.lower() or "/asset.pdf" in path


def crawl(url: str, get_page=fetch_page) -> dict:
    """Crawl the company's site: {"candidates": [(score, pdf url, link text)] best first, "fetched": pages read, "blocked": pages refused}."""
    hint = hint_from(url)
    site = registrable_domain(urlsplit(url).hostname or "")
    queue = deque((p, 0) for p in start_pages(url))
    seen, pdfs, fetched, blocked = set(), {}, 0, 0
    while queue and fetched < MAX_PAGES:
        page, depth = queue.popleft()
        if page in seen:
            continue
        seen.add(page)
        try:
            html, final = get_page(page)
        except FetchError as error:
            blocked += "HTTP 403" in str(error) or "HTTP 401" in str(error)
            continue
        fetched += 1
        for link, text in extract_links(html, final):
            if is_pdf_link(link):
                score = score_link(link, text, hint)
                if score > pdfs.get(link, (-99, ""))[0]:
                    pdfs[link] = (score, text)
            elif depth < MAX_DEPTH and registrable_domain(urlsplit(link).hostname or "") == site and INTEREST.search(f"{link} {text}"):
                if link not in seen and not re.search(r"\.(jpe?g|png|gif|svg|zip|xlsx?|docx?|pptx?|mp4)(\?|$)", link, re.I):
                    # pages whose address or wording is about sustainability are looked at first
                    (queue.appendleft if REPORT_WORDS.search(f"{link} {text}") else queue.append)((link, depth + 1))
    ranked = sorted(((s, u, t) for u, (s, t) in pdfs.items()), key=lambda r: -r[0])
    minimum = 6 if hint["year"] else 3
    return {"candidates": [r for r in ranked if r[0] >= minimum], "fetched": fetched, "blocked": blocked}


def find_candidates(url: str, get_page=fetch_page) -> list[tuple[int, str, str]]:
    return crawl(url, get_page)["candidates"]


def looks_like_the_report(pdf_path: Path, hint: dict) -> bool:
    """The downloaded PDF must be a sustainability / ESG document of the year we were looking for."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(pdf_path)
        opening = " ".join((reader.pages[i].extract_text() or "") for i in range(min(3, len(reader.pages))))
    except Exception:
        return False
    if not REPORT_WORDS.search(opening):
        return False
    return not hint["year"] or str(hint["year"]) in opening or str(hint["year"] + 1) in opening or str(hint["year"] - 1) in opening


def discover_report(url: str, dest_dir: str | Path, get_page=fetch_page, fetch_pdf=download) -> tuple[Path, dict, str]:
    """Return (pdf path, fetch info, official url) for the report, or raise FetchError saying exactly what happened."""
    found = crawl(url, get_page)
    candidates = found["candidates"]
    if not candidates and found["fetched"] == 0 and found["blocked"]:
        raise FetchError("The company's website refuses automated access (HTTP 403 on its own pages), so the report could not be located "
                         "automatically. That does not mean the report is unavailable: find it on the company's publications page in a browser "
                         "and run the extractor on the downloaded PDF.", 403)
    if not candidates:
        raise FetchError("The link does not work and no matching report was found on the company's website.", 404)
    hint = hint_from(url)
    blocked = None
    for score, link, text in candidates[:TRY_PDFS]:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                path, info = fetch_pdf(link, tmp)
            except FetchError as error:
                if "HTTP 403" in str(error) or "HTTP 401" in str(error):
                    blocked = blocked or link
                continue
            if looks_like_the_report(path, hint):
                final = Path(dest_dir) / "found.pdf"
                final.write_bytes(path.read_bytes())
                return final, info, link
    if blocked:
        raise FetchError(f"The report is on the company's website ({blocked}) but that server refuses automated downloads "
                         f"(HTTP 403); download it in a browser and run the extractor on the file.", 403)
    raise FetchError("The link does not work, and the PDFs found on the company's website did not match the report.", 404)
