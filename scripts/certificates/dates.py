"""The reporting period, exactly as the report states it (and its start and end dates when it gives them).

Every candidate found in the text is scored on how clearly it is about the report itself ("This report covers ...",
"Reporting period: ...") and on how well it fits the report's own year; the best one wins. Candidates that are
about something else (a survey, a subsidiary's 15-month year, a 2030 target) are rejected.
"""
import calendar
import re
from datetime import date

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_M = "|".join(m.capitalize() for m in MONTHS)
_ORD = r"(?:\s?(?:st|nd|rd|th))?"
_DAY_MONTH = rf"(?:\d{{1,2}}{_ORD}\s+(?:{_M})|(?:{_M})\s+\d{{1,2}}{_ORD})"
_NUMERIC = r"(?:\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2})"
_FULL = rf"(?:{_DAY_MONTH},?\s+\d{{4}}|{_NUMERIC})"
_SEP = r"\s*,?\s*(?:-|–|—|(?:up\s+)?to(?:\s+and\s+including)?|until|through(?:\s+and\s+(?:as\s+of|including))?)\s*"
_MONTH_YEAR = rf"(?:{_M})\s+\d{{4}}"

RANGE = re.compile(rf"(?P<a>{_FULL}|{_DAY_MONTH}){_SEP}(?P<b>{_FULL})", re.I)
MONTH_RANGE = re.compile(rf"(?P<a>{_MONTH_YEAR}){_SEP}(?P<b>{_MONTH_YEAR})", re.I)
YEAR_TO = re.compile(rf"\b(?:year|period)\s+(?:to|ended|ending)\s+(?:on\s+)?(?P<b>{_FULL})", re.I)
CALENDAR = re.compile(
    r"calendar\s+year\s+(?P<y1>20\d\d)\b|\b(?P<y2>20\d\d)\s+calendar\s+year|"
    r"\byear\s+(?P<y3>20\d\d)\W{1,8}(?:which\s+)?(?:coincides|corresponds)\s+(?:with\s+)?the\s+calendar\s+year",
    re.I,
)
YEAR_LABEL = re.compile(
    r"\b(?:(?:financial|fiscal)\s+year\s+(?P<a>20\d\d)|FY\s?(?P<b>\d{2,4})|(?P<c>20\d\d)\s+(?:financial|fiscal)\s+year|"
    r"reporting\s+year\s+(?:to\s+which[^.]{0,80}?\s+(?:refer|relate)s?\s+is\s+)?(?P<d>20\d\d)|(?P<e>20\d\d)\s+reporting\s+year)\b",
    re.I,
)
# the sentence is about the report itself, not about some other figure
SELF = re.compile(
    r"\b(?:this|the|our)\s+(?:[\w&-]+\s+){0,3}(?:report|statement|document|databook|data\s?book|index|publication)\b|"
    r"\breport(?:ing)?\s+(?:period|year|scope|boundary)|\bperiod\s+covered|\bscope\s+of\s+(?:this|the)|\ball\s+information\b|"
    r"\bkey\s+figures\b|\binformation\s+and\s+data\b|\bcovering\s+the\s+same\s+period|\bthe\s+report\b|\bsustainability\s+information\b",
    re.I,
)
COVER = re.compile(r"\bperiod\b|\bcover|\bencompass|\bapplies\s+to|\bpertain|\brefer(?:s)?\s+to|\bbased\s+on\b|\breported\b", re.I)
OTHER = re.compile(
    r"baseline|target|compar|previous|prior\b|restat|forecast|expected|will\b|\bplan|outlook|ambition|by\s+20\d\d|since\s+\d|"
    r"survey|insurance|results\s+cover|joint\s+venture",
    re.I,
)
KIND_BONUS = {"range": 4, "calendar": 3, "months": 2, "year_to": 2, "label": 0}


def unbreak(text: str) -> str:
    """Rejoin words split across lines by hyphenation ("De - cember" -> "December")."""
    return re.sub(r"(?<=[A-Za-z]) - (?=[a-z])", "", " ".join(text.split()))


def _parse(token: str, year: int | None = None) -> date | None:
    token = re.sub(r"\s+", " ", token.strip())
    if m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", token):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", token):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.search(rf"(?:(?P<d1>\d{{1,2}}){_ORD}\s+(?P<m1>{_M})|(?P<m2>{_M})\s+(?P<d2>\d{{1,2}}){_ORD})(?:,?\s+(?P<y>\d{{4}}))?", token, re.I)
        if not m:
            return None
        d = int(m["d1"] or m["d2"])
        mo = MONTHS.index((m["m1"] or m["m2"]).lower()) + 1
        y = int(m["y"]) if m["y"] else year
    try:
        return date(y, mo, d) if y else None
    except ValueError:
        return None


def _month_start(token: str) -> date | None:
    m = re.fullmatch(rf"({_M})\s+(\d{{4}})", token.strip(), re.I)
    return date(int(m[2]), MONTHS.index(m[1].lower()) + 1, 1) if m else None


def _month_end(token: str) -> date | None:
    first = _month_start(token)
    return first.replace(day=calendar.monthrange(first.year, first.month)[1]) if first else None


def _year_before(end: date) -> date:
    try:
        return end.replace(year=end.year - 1) + (date(2000, 1, 2) - date(2000, 1, 1))
    except ValueError:  # 29 February
        return date(end.year - 1, 2, 28) + (date(2000, 1, 2) - date(2000, 1, 1))


def _sentence(hay: str, span: tuple[int, int]) -> tuple[str, int, int]:
    """The sentence holding the candidate, and the candidate's position inside it."""
    lo = max(0, span[0] - 300)
    breaks = list(re.finditer(r"[.!?;]\s+(?=[A-Z(\[\u2022\d])", hay[lo: span[0]]))
    start = lo + breaks[-1].end() if breaks else lo
    after = hay[span[1]: span[1] + 250]
    stop = re.search(r"[.!?]\s+(?=[A-Z(\[\u2022])", after)
    end = span[1] + (stop.start() + 1 if stop else len(after))
    return hay[start:end], span[0] - start, span[1] - start


def _candidates(text: str, from_statement: bool) -> list[dict]:
    found = []
    for m in RANGE.finditer(text):
        end = _parse(m["b"])
        start = _parse(m["a"], end.year if end else None)
        if not (start and end):
            continue
        if start > end:
            if re.search(r"\d{4}|\d\.\d", m["a"]):
                continue  # both years are written and the start is after the end: a typo in the report, not a period
            start = start.replace(year=start.year - 1)  # "1 July to 30 June 2025"
        if 250 <= (end - start).days <= 400:
            found.append({"kind": "range", "start": start, "end": end, "text": " ".join(m.group(0).split()), "pos": m.start(), "span": m.span()})
    for m in MONTH_RANGE.finditer(text):
        start, end = _month_start(m["a"]), _month_end(m["b"])
        if start and end and 330 <= (end - start).days <= 400:
            found.append({"kind": "months", "start": start, "end": end, "text": " ".join(m.group(0).split()), "pos": m.start(), "span": m.span()})
    for m in YEAR_TO.finditer(text):
        end = _parse(m["b"])
        if end:
            found.append({"kind": "year_to", "start": _year_before(end), "end": end, "text": " ".join(m.group(0).split()), "pos": m.start(), "span": m.span()})
    for m in CALENDAR.finditer(text):
        year = int(next(g for g in (m["y1"], m["y2"], m["y3"]) if g))
        found.append({"kind": "calendar", "start": date(year, 1, 1), "end": date(year, 12, 31), "text": f"calendar year {year}",
                      "pos": m.start(), "span": m.span(), "year": year})
    for m in YEAR_LABEL.finditer(text):
        year = int(next(g for g in (m["a"], m["b"], m["c"], m["d"], m["e"]) if g))
        year += 2000 if year < 100 else 0
        found.append({"kind": "label", "start": None, "end": None, "text": " ".join(m.group(0).split()), "pos": m.start(), "span": m.span(), "year": year})
    for c in found:
        c["from_statement"] = from_statement
    return found


def find_period(texts: list[str], scope_statement: str | None, reporting_year: int | None = None, debug: bool = False,
                derive_start: bool = False):
    """The reporting period as the report states it.

    Dates are returned only when the report gives them: a full range, whole months ("April 2022 to March 2023" is read as
    1 April 2022 to 31 March 2023), or a named calendar year (January to December by definition). A year label such as
    "FY2024" gives no dates. A report that states only a year end ("year ended 31 December 2023") gives an end date and no start
    date, unless derive_start is set, in which case the start is taken to be the day after one year earlier (an assumption)."""
    full = unbreak("\n".join(texts))
    nothing = {"periodText": None, "startDate": None, "endDate": None, "basis": "not stated in the report", "text": None}

    def fits(year: int | None) -> bool:  # the year read from the cover can be the publication year, so allow one either side
        return reporting_year is None or (year is not None and abs(year - reporting_year) <= 1)

    pool = []
    if scope_statement:
        pool += _candidates(unbreak(scope_statement), True)
    pool += [dict(c, hay=full) for c in _candidates(full, False)]
    scored = []
    for c in pool:
        hay = c.get("hay") or unbreak(scope_statement or "")
        ctx, rel_start, rel_end = _sentence(hay, c["span"])
        near = ctx[max(0, rel_start - 110): rel_end + 60]  # negative words only count close to the dates
        year = c.get("year") or (c["end"].year if c["end"] else None)
        if not fits(year):
            continue
        selfref = bool(SELF.search(ctx))
        if c["kind"] != "label" and not (selfref or c["from_statement"]):
            continue  # a date range that is not about the report (a survey, a subsidiary, a footnote)
        score = KIND_BONUS[c["kind"]] + (6 if selfref else 0) + (3 if c["from_statement"] else 0) + (2 if COVER.search(ctx) else 0)
        score -= 4 if OTHER.search(near) else 0
        if reporting_year is not None and year == reporting_year:
            score += 2
        scored.append((score, -c["pos"], c))
    if debug:
        return sorted([(s, c["kind"], c["text"][:50]) for s, _, c in scored], key=lambda x: -x[0])
    if not scored:
        return nothing
    best = max(scored, key=lambda s: (s[0], s[1]))[2]
    if best["kind"] == "year_to" and not derive_start:
        return {"periodText": best["text"], "startDate": None, "endDate": best["end"].isoformat(),
                "basis": "only the end date is stated", "text": best["text"]}
    if best["kind"] == "label":
        # several year labels may appear: take the year the report is about, then the most frequent one
        labels = [c for _, _, c in scored if c["kind"] == "label"]
        years = [c["year"] for c in labels]
        pick = max(labels, key=lambda c: ((c["year"] == reporting_year), years.count(c["year"]), -c["pos"]))
        return {**nothing, "periodText": pick["text"]}
    basis = {"range": "stated", "months": "stated (whole months)", "calendar": "stated (calendar year)",
             "year_to": "end date stated; start derived as the first day of that 12-month year (assumption)"}[best["kind"]]
    return {"periodText": best["text"], "startDate": best["start"].isoformat(),
            "endDate": best["end"].isoformat(), "basis": basis, "text": best["text"]}


def report_dates(texts: list[str], scope_statement: str | None, reporting_year: int | None = None, derive_start: bool = False) -> dict:
    period = find_period(texts, scope_statement, reporting_year, derive_start=derive_start)
    return {k: period[k] for k in ("startDate", "endDate", "basis", "text")}
