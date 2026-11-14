"""Work out which company a report belongs to, from its URL, file name and text.

Evidence is cross-checked: the domain gives a reliable but run-together label ("fonderieariotti"), the text gives
properly spelled names ("Fonderie Ariotti", "Castings PLC"), and agreement between them is what makes a name confident.
"""
import re
from collections import Counter
from urllib.parse import unquote, urlsplit

LEGAL_FORMS = (
    r"plc|PLC|P\.L\.C\.|Ltd\.?|Limited|Inc\.?|Corp\.?|Corporation|LLC|GmbH(?: & Co\. KG)?|AG|SE|S\.p\.A\.?|SpA|"
    r"S\.r\.l\.?|Srl|S\.A\.?|N\.V\.|NV|B\.V\.|AB|ASA|Oyj|A/S|KG|Co\."
)
LEGAL_NAME = re.compile(r"((?:[A-Z][\w&.'’-]*\s){1,5}?)(" + LEGAL_FORMS + r")(?=[\s,.;:)]|$)")
WORD = re.compile(r"[A-Z][\w&'’-]*")
SECOND_LEVEL = {"co", "com", "org", "net", "plc", "ltd", "ac", "gov", "edu"}
REPORT_WORDS = {"annual", "sustainability", "esg", "report", "reports", "integrated", "csr", "climate", "impact",
                "statement", "year", "review", "interactive", "web", "final", "doc", "document", "file", "pdf"}
LEGAL_CASE = {"plc": "PLC", "gmbh": "GmbH", "ag": "AG", "ltd": "Ltd", "inc": "Inc", "llc": "LLC", "spa": "S.p.A.",
              "srl": "S.r.l.", "nv": "N.V.", "bv": "B.V.", "se": "SE", "ab": "AB", "asa": "ASA", "sa": "S.A."}
GENERIC_NAME_WORDS = {"group", "company", "corporate", "global", "the", "our", "annual", "esg"}
FIRST_PAGES = 5  # mentions on the opening pages count extra


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def host_label(url: str | None) -> str | None:
    """'www.fonderieariotti.com' -> 'fonderieariotti'; 'castings.plc.uk' -> 'castings'."""
    host = (urlsplit(url or "").hostname or "").lower()
    labels = [l for l in host.split(".") if l and l != "www"]
    if len(labels) >= 2:
        labels = labels[:-1]  # top-level domain
        if len(labels) >= 2 and labels[-1] in SECOND_LEVEL:
            labels = labels[:-1]
    return _key(labels[-1]) if labels else None  # letters and digits only: "borgautomotive-group" -> "borgautomotivegroup"


def _file_name_candidate(url: str | None) -> str | None:
    stem = re.sub(r"\.pdf$", "", unquote(urlsplit(url or "").path.rsplit("/", 1)[-1]), flags=re.I)
    leading = []
    for token in re.split(r"[-_\s]+", stem):
        if token.lower() in REPORT_WORDS or re.fullmatch(r"20\d\d", token):
            break
        leading.append(token)
    leading = [t for t in leading if t.isalpha() and len(t) >= 2]
    if not leading or len(leading) != len(re.split(r"[-_\s]+", stem)[: len(leading)]):
        return None
    if all(t.lower() in GENERIC_NAME_WORDS for t in leading):
        return None
    return " ".join(LEGAL_CASE.get(t.lower(), t.capitalize()) for t in leading)


def _strip_legal(name: str) -> str:
    return re.sub(r"\s+(?:" + LEGAL_FORMS + r")$", "", name).strip()


def _label_mentions(tokens: list[str], label: str) -> Counter:
    """Capitalised word runs whose letters spell the domain label, e.g. 'Fonderie Ariotti' for 'fonderieariotti'."""
    found = Counter()
    keys = [_key(t) for t in tokens]
    for i in range(len(tokens)):
        built = ""
        for j in range(i, min(i + 4, len(tokens))):
            built += keys[j]
            if built == label:
                found[" ".join(tokens[i : j + 1])] += 1
            if len(built) >= len(label):
                break
    return found


def detect_company(url: str | None, texts: list[str]) -> dict:
    label = host_label(url)
    flat = [" ".join(t.split()) for t in texts]

    legal = Counter()
    for page, text in enumerate(flat):
        weight = 3 if page < FIRST_PAGES else 1
        for m in LEGAL_NAME.finditer(text):
            words = m.group(1).split()
            while words and words[0] in {"The", "Our", "At", "By", "For", "With"}:
                words = words[1:]
            if words:
                legal[" ".join(words) + " " + m.group(2).rstrip(".")] += weight

    tokens = WORD.findall(" ".join(flat))
    spelled = _label_mentions(tokens, label) if label else Counter()
    from_file = _file_name_candidate(url)

    candidates = []
    for name, score in legal.items():
        short = _strip_legal(name)
        agrees = bool(label) and (_key(short).startswith(label) or label.startswith(_key(short)) and len(_key(short)) >= 4)
        candidates.append({"name": name, "shortName": short, "source": "content" + ("+url" if agrees else ""),
                           "mentions": score, "_rank": score + (1000 if agrees else 0)})
    for name, count in spelled.items():
        if not any(_key(c["shortName"]) == _key(name) for c in candidates):
            candidates.append({"name": name, "shortName": name, "source": "content+url", "mentions": count,
                               "_rank": 500 + count})
    if from_file:
        candidates.append({"name": from_file, "shortName": _strip_legal(from_file), "source": "file name",
                           "mentions": None, "_rank": 50})
    if label:
        candidates.append({"name": label.capitalize(), "shortName": label.capitalize(), "source": "url",
                           "mentions": None, "_rank": 10})

    if not candidates:
        return {"name": None, "shortName": None, "source": None, "confidence": None, "candidates": []}
    candidates.sort(key=lambda c: -c["_rank"])
    seen, unique = set(), []
    for c in candidates:  # keep the best-evidenced entry for each name
        if _key(c["name"]) not in seen:
            seen.add(_key(c["name"]))
            unique.append(c)
    candidates = unique
    best = candidates[0]
    confidence = "high" if "content+url" in best["source"] or "+url" in best["source"] else (
        "medium" if best["source"] == "content" and (best["mentions"] or 0) >= 3 else "low")
    return {
        "name": best["name"], "shortName": best["shortName"], "source": best["source"], "confidence": confidence,
        "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates[:5]],
    }
