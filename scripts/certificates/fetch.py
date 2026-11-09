"""Safe URL download + metadata taken from the URL itself.

The service fetches URLs supplied by callers, so every hop is checked against SSRF:
http(s) only, ports 80/443 only, and the host must resolve to public IP addresses.
Set ALLOWED_HOSTS=host1,host2 to restrict downloads to specific hosts (recommended in production).
ALLOW_PRIVATE_HOSTS=1 disables the address checks (tests / local development only).
"""
import ipaddress
import os
import posixpath
import re
import socket
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

MAX_BYTES = int(os.getenv("MAX_PDF_MB", "100")) * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = (10, 60)  # connect, read
USER_AGENT = "certificate-extractor/1.0"
TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|msclkid|mc_cid|mc_eid|ref|ref_src)$", re.I)
LANGUAGES = {"en", "de", "fr", "it", "es", "pt", "nl", "sv", "da", "fi", "pl", "cs", "ja", "zh"}


class FetchError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _private_ok() -> bool:
    return os.getenv("ALLOW_PRIVATE_HOSTS") == "1"


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("Only absolute http(s) URLs are accepted.", 400)
    host = parts.hostname.lower()

    allowed = [h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
    if allowed and not any(host == h or host.endswith("." + h) for h in allowed):
        raise FetchError(f"Host not allowed: {host}", 403)

    if _private_ok():
        return
    if parts.port not in (None, 80, 443):
        raise FetchError("Only ports 80 and 443 are allowed.", 403)

    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise FetchError(f"Host resolves to a non-public address: {host}", 403)
    try:
        literal = {str(ipaddress.ip_address(host))}
    except ValueError:
        literal = set()
    if not literal and _via_proxy(url):
        # Behind an HTTP proxy the proxy resolves names (and this machine often cannot), so a local
        # lookup would be both impossible and meaningless. The proxy's egress policy is the control here.
        return
    try:
        addresses = literal or {info[4][0] for info in socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)}
    except socket.gaierror:
        raise FetchError(f"Could not resolve host: {host}", 502)
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise FetchError(f"Host resolves to a non-public address: {host}", 403)


def _via_proxy(url: str) -> bool:
    return not requests.utils.should_bypass_proxies(url, None) and bool(
        requests.utils.select_proxy(url, requests.utils.get_environ_proxies(url))
    )


def download(url: str, dest_dir: str | Path) -> tuple[Path, dict]:
    """Download a PDF, following redirects manually so each hop is re-checked."""
    chain = []
    session = requests.Session()
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        check_url(current)
        try:
            resp = session.get(current, stream=True, allow_redirects=False, timeout=TIMEOUT,
                               headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.5"})
        except requests.Timeout:
            raise FetchError("Timed out fetching the URL.", 504)
        except requests.exceptions.ProxyError:
            raise FetchError("The network proxy refused or could not reach this host (check its egress allowlist).", 502)
        except requests.RequestException as error:
            raise FetchError(f"Could not fetch the URL: {error.__class__.__name__}", 502)
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            target = resp.headers.get("Location")
            resp.close()
            if not target:
                raise FetchError("Redirect without a Location header.", 502)
            chain.append(current)
            current = urljoin(current, target)
            continue
        break
    else:
        raise FetchError("Too many redirects.", 502)

    with resp:
        if resp.status_code != 200:
            raise FetchError(f"The server answered HTTP {resp.status_code}.", 502)
        declared = resp.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise FetchError(f"File is larger than {MAX_BYTES // 1024 // 1024} MB.", 413)

        path = Path(dest_dir) / "download.pdf"
        size = 0
        with open(path, "wb") as out:
            for block in resp.iter_content(64 * 1024):
                size += len(block)
                if size > MAX_BYTES:
                    raise FetchError(f"File is larger than {MAX_BYTES // 1024 // 1024} MB.", 413)
                out.write(block)
        headers = resp.headers

    with open(path, "rb") as f:
        head = f.read(65536)
    if not head.startswith(b"%PDF-"):
        kind = (headers.get("Content-Type") or "unknown content type").split(";")[0]
        title = re.search(rb"<title[^>]*>(.*?)</title>", head, re.S | re.I)
        page = f' titled "{" ".join(title.group(1).decode("utf-8", "replace").split())[:80]}"' if title else ""
        raise FetchError(f"The URL did not return a PDF (got {kind}{page}). The link may be broken or moved.", 415)

    return path, {
        "finalUrl": current,
        "redirects": chain,
        "bytes": size,
        "contentType": headers.get("Content-Type"),
        "lastModified": headers.get("Last-Modified"),
        "etag": headers.get("ETag"),
    }


def url_metadata(url: str) -> dict:
    """Facts that can be read from the URL alone (no download)."""
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if not TRACKING.match(k)]
    canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(kept), ""))

    segments = [s for s in parts.path.split("/") if s]
    filename = posixpath.basename(parts.path)
    stem = re.sub(r"\.pdf$", "", filename, flags=re.I)

    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", stem) or re.search(r"(?<!\d)(20\d{2})(?!\d)", parts.path)
    language = next((s.lower() for s in reversed(segments[:-1]) if s.lower() in LANGUAGES), None)
    suffix = re.search(r"[-_]([a-z]{2})$", stem, re.I)
    if not language and suffix and suffix.group(1).lower() in LANGUAGES:
        language = suffix.group(1).lower()

    slug = re.sub(r"(?<!\d)20\d{2}(?!\d)", " ", stem)
    slug = re.sub(r"[-_]([a-z]{2})$", " ", slug, flags=re.I) if language else slug
    document_type = re.sub(r"[-_\s]+", " ", slug).strip() or None

    return {
        "url": url,
        "canonicalUrl": canonical,
        "strippedParameters": [k for k, _ in pairs if TRACKING.match(k)],
        "host": parts.hostname,
        "fileName": filename or None,
        "year": int(year_match.group(1)) if year_match else None,
        "language": language,
        "documentType": document_type,
    }
