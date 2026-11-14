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
LEGAL_NAME = re.compile(r"((?:[A-Z][\w&.'’-]*,?\s){1,5}?)(" + LEGAL_FORMS + r")(?=[\s,.;:)]|$)")
WORD = re.compile(r"[A-Z][\w&'’-]*")
SECOND_LEVEL = {"co", "com", "org", "net", "plc", "ltd", "ac", "gov", "edu"}
REPORT_WORDS = {"annual", "sustainability", "esg", "report", "reports", "integrated", "csr", "climate", "impact",
                "statement", "year", "review", "interactive", "web", "final", "doc", "document", "file", "pdf"}
LEGAL_CASE = {"plc": "PLC", "gmbh": "GmbH", "ag": "AG", "ltd": "Ltd", "inc": "Inc", "llc": "LLC", "spa": "S.p.A.",
              "srl": "S.r.l.", "nv": "N.V.", "bv": "B.V.", "se": "SE", "ab": "AB", "asa": "ASA", "sa": "S.A."}
GENERIC_NAME_WORDS = {"group", "company", "corporate", "global", "the", "our", "annual", "esg"}
FIRST_PAGES = 5
RUN = re.compile(r"[A-Z][\w&'’-]*(?:\s+(?:[A-Z][\w&'’-]*|&))*")
EDGE_WORDS = {"the", "our", "we", "in", "at", "for", "and", "of", "a", "an", "this", "that", "these", "with", "by", "on", "to",
              "as", "from", "page", "see", "all", "it", "its", "their", "is", "are", "was", "were", "&", "or", "per"}
GENERIC_WORDS = set((
    "sustainability report reports annual esg statement board message chapter table contents index environmental social governance "
    "performance health safety climate energy emissions carbon waste water materiality stakeholders stakeholder employees diversity "
    "human rights ethics code conduct policy policies management strategy strategic risk risks data key figures total europe european "
    "asia america africa united states north south east west kingdom january february march april may june july august september "
    "october november december monday tuesday wednesday thursday friday saturday sunday scope topic standard standards disclosure "
    "disclosures gri esrs csrd tcfd sasb issb cdp taxonomy product products customers suppliers supplier community communities "
    "introduction foreword overview about appendix glossary references assurance independent limited audit auditor corporate "
    "social responsibility csr impact goals targets objectives progress results year years").split())
ORG_WORDS = set((
    "group foundry foundries fonderie fonderia giesserei gießerei castings casting industries industrie holding holdings company "
    "corporation corp technologies technology automotive metals steel engineering manufacturing systems solutions products "
    "international enterprises partners works plc ltd limited gmbh ag inc llc spa sa nv bv ab asa oyj").split())


ABBREVIATIONS = {"wm", "st", "co", "inc", "corp", "ltd", "mr", "dr", "no", "bros", "intl"}
AUDITORS = re.compile(r"pricewaterhouse|\bpwc\b|kpmg|deloitte|ernst|\bey\b|\bbdo\b|grant thornton|\btrc\b", re.I)
STARTERS = EDGE_WORDS | {"since", "during", "while", "when", "after", "before", "today", "here", "however", "also", "but", "thanks",
                         "through", "across", "within", "about", "moreover", "furthermore", "additionally", "therefore", "overall",
                         "further", "last", "next", "each", "every", "both", "some", "many", "most", "other", "new", "more"}
SUBJECT_VERBS = (r"(?:is|are|was|were|has|have|had|operates|employs|reported|produces|manufactures|moved|serves|supplies|aims|"
                 r"continues|expects|believes|remains|offers|provides|develops|became|joined|achieved|invested|launched|committed)")


def _plausible(short: str) -> bool:
    """Rule out table codes ("AA"), abbreviations ("WFI"), headings, auditors and sentence openers."""
    words = short.split()
    low = [w.lower() for w in words]
    if not words or AUDITORS.search(short) or low[0] in STARTERS or any(w in GENERIC_WORDS for w in low):
        return False
    if any(len(w) <= 2 and w.isupper() for w in words):
        return False
    return not (len(words) == 1 and words[0].isupper() and len(words[0]) <= 4)


def _subject_names(flat: list[str]) -> Counter:
    """Capitalised phrases that are the subject of a sentence: "BORG Automotive Group reported ...", "X is headquartered ...".
    Headings and topics rarely do that, so this separates a company from section titles like "Supply Chain"."""
    found, surface = Counter(), {}
    for text in flat:
        for m in RUN.finditer(text):
            if not re.match(r"(?:[’']s)?\s+" + SUBJECT_VERBS + r"\b", text[m.end(): m.end() + 40]):
                continue
            tokens = [re.sub(r"[’']s$", "", t) for t in m.group(0).split()]
            for i in range(max(0, len(tokens) - 4), len(tokens)):  # the name is the tail of the capitalised run
                window = tokens[i:]
                if len(window) >= 2 and _plausible(" ".join(window)):
                    key = " ".join(w.lower() for w in window)
                    found[key] += 1
                    surface.setdefault(key, Counter())[" ".join(window)] += 1
    return Counter({surface[k].most_common(1)[0][0]: v for k, v in found.items()})


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

    legal, legal_raw = Counter(), Counter()
    for page, text in enumerate(flat):
        weight = 3 if page < FIRST_PAGES else 1
        for m in LEGAL_NAME.finditer(text):
            words = m.group(1).replace(",", "").split()
            for i in range(len(words) - 1, -1, -1):  # a word ending a sentence ("Switzerland.") cannot belong to the name after it
                if words[i].endswith(".") and len(words[i]) > 3 and words[i].rstrip(".").lower() not in ABBREVIATIONS:
                    words = words[i + 1:]
                    break
            while words and words[0] in {"The", "Our", "At", "By", "For", "With"}:
                words = words[1:]
            if words and _plausible(" ".join(words)):
                form = m.group(2).rstrip(".")
                name = " ".join(words) + " " + (form + "." if form.lower() in {"inc", "corp", "co"} else form)
                legal[name] += weight
                legal_raw[name] += 1

    all_text = " ".join(flat)
    tokens = WORD.findall(all_text)
    spelled = _label_mentions(tokens, label) if label else Counter()
    subjects = _subject_names(flat)
    from_file = _file_name_candidate(url)

    def mentions_of(name: str) -> int:
        return len(re.findall(r"(?<!\w)" + re.escape(name) + r"(?!\w)", all_text, re.I))

    candidates = []
    for name, score in legal.items():
        short = _strip_legal(name)
        agrees = bool(label) and (_key(short).startswith(label) or label.startswith(_key(short)) and len(_key(short)) >= 4)
        # the parent is the entity the report talks about: its short name recurs far more often than a subsidiary's
        subject_hits = next((n for s, n in subjects.items() if _key(s) == _key(short)), 0)
        formal = 100 if legal_raw[name] >= 3 else 0  # stated formally several times: that is the entity, not a division
        rank = 3 * score + mentions_of(short) + 5 * subject_hits + formal + (1000 if agrees else 0)
        candidates.append({"name": name, "shortName": short, "source": "content" + ("+url" if agrees else ""),
                           "mentions": score, "_rank": rank})
    for name, count in subjects.items():
        if count >= 2 and not any(_key(c["shortName"]) == _key(name) for c in candidates):
            agrees = bool(label) and _key(name).startswith(label)
            candidates.append({"name": name, "shortName": name, "source": "content" + ("+url" if agrees else ""),
                               "mentions": count, "_rank": 5 * count + (1000 if agrees else 0)})
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
    if best["source"] == "content" and best["mentions"] and best["name"] == best["shortName"]:
        legal_match = next((x for x in candidates if x is not best and x["shortName"] != x["name"]
                            and _key(x["shortName"]) == _key(best["name"])), None)
        if legal_match:
            best = {**best, "name": legal_match["name"]}
    confidence = "high" if "content+url" in best["source"] or "+url" in best["source"] else (
        "medium" if best["source"] == "content" and (best["mentions"] or 0) >= 3 else "low")
    return {
        "name": best["name"], "shortName": best["shortName"], "source": best["source"], "confidence": confidence,
        "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates[:5]],
    }
