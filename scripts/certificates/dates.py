"""Start and end date of the reporting period, only when the report states them (nothing is inferred)."""
import re
from datetime import date

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_M = "|".join(m.capitalize() for m in MONTHS)
_DAY_MONTH = rf"(?:(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<m1>{_M})|(?P<m2>{_M})\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?)"
_FULL = rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_M})|(?:{_M})\s+\d{{1,2}}(?:st|nd|rd|th)?),?\s+\d{{4}}"
RANGE = re.compile(
    rf"(?P<a>{_FULL}|\d{{1,2}}\s+(?:{_M})|(?:{_M})\s+\d{{1,2}})\s*(?:-|–|—|to|until|through)\s*(?P<b>{_FULL})", re.I
)
YEAR_TO = re.compile(rf"\b(?:year|period)\s+(?:to|ended|ending)\s+(?P<b>{_FULL})", re.I)
CONTEXT = re.compile(r"period|reporting|fiscal|financial|year|cover|from|encompass", re.I)


def unbreak(text: str) -> str:
    """Rejoin words split across lines by hyphenation ("De - cember" -> "December")."""
    return re.sub(r"(?<=[A-Za-z]) - (?=[a-z])", "", " ".join(text.split()))


def _parse(token: str, year: int | None = None) -> date | None:
    m = re.search(_DAY_MONTH + r"(?:,?\s+(?P<y>\d{4}))?", token, re.I)
    if not m:
        return None
    day = int(m["d1"] or m["d2"])
    month = MONTHS.index((m["m1"] or m["m2"]).lower()) + 1
    y = int(m["y"]) if m["y"] else year
    try:
        return date(y, month, day) if y else None
    except ValueError:
        return None


FY_TEXT = re.compile(
    r"\b(?:(?:calendar|financial|fiscal) year (?:ended? )?(?P<y1>\d{4})|FY\s?(?P<y2>\d{2,4})|(?P<y3>20\d{2}) (?:financial|fiscal) year)\b", re.I
)


def find_period(texts: list[str], scope_statement: str | None, reporting_year: int | None = None) -> dict:
    """The reporting period exactly as the report states it. Returns the text as written and, when the report gives
    them, the start and end dates. Candidates that do not fit the report's own year (a 2030 target, last year's
    figures, a range that is not about a year long) are ignored, and nothing is inferred."""
    full = unbreak("\n".join(texts))
    nothing = {"periodText": None, "startDate": None, "endDate": None, "basis": "not stated in the report", "text": None}

    def year_ok(year: int | None) -> bool:  # the "reporting year" read from the cover can be the publication year, so allow one either side
        return reporting_year is None or (year is not None and abs(year - reporting_year) <= 1)

    def from_range(hay: str, need_context: bool):
        for m in RANGE.finditer(hay):
            if need_context and not CONTEXT.search(hay[max(0, m.start() - 90): m.start()]):
                continue
            end = _parse(m["b"])
            start = _parse(m["a"], end.year if end else None)
            if start and end:
                if start > end:  # "1 July to 30 June 2024": the start falls in the year before
                    start = start.replace(year=start.year - 1)
                if 250 <= (end - start).days <= 400 and year_ok(end.year):
                    return start, end, " ".join(m.group(0).split())
        return None

    hit = (from_range(unbreak(scope_statement), False) if scope_statement else None) or from_range(full, True)
    if hit:
        return {"periodText": hit[2], **_result(hit[0], hit[1], "stated", hit[2])}
    for m in YEAR_TO.finditer(full):
        end = _parse(m["b"])
        if end and year_ok(end.year):  # only the end is stated; the start is left empty rather than guessed
            return {"periodText": None, "startDate": None, "endDate": end.isoformat(),
                    "basis": "only the end date is stated", "text": " ".join(m.group(0).split())}
    for m in FY_TEXT.finditer(full):
        year = next(int(g) for g in (m["y1"], m["y2"], m["y3"]) if g)
        year += 2000 if year < 100 else 0
        if year_ok(year):
            return {**nothing, "periodText": " ".join(m.group(0).split())}
    return nothing


def report_dates(texts: list[str], scope_statement: str | None, reporting_year: int | None = None) -> dict:
    period = find_period(texts, scope_statement, reporting_year)
    return {k: period[k] for k in ("startDate", "endDate", "basis", "text")}


def _result(start: date, end: date, basis: str, text: str | None) -> dict:
    return {"startDate": start.isoformat(), "endDate": end.isoformat(), "basis": basis, "text": text}
