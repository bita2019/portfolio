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
CONTEXT = re.compile(r"period|reporting|fiscal|financial|year|covering|from|encompass", re.I)


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


def report_dates(texts: list[str], scope_statement: str | None) -> dict:
    full = unbreak("\n".join(texts))

    def from_range(hay: str, need_context: bool):
        for m in RANGE.finditer(hay):
            if need_context and not CONTEXT.search(hay[max(0, m.start() - 90): m.start()]):
                continue
            end = _parse(m["b"])
            start = _parse(m["a"], end.year if end else None)
            if start and end:
                if start > end:  # "1 July to 30 June 2024": the start falls in the year before
                    start = start.replace(year=start.year - 1)
                return start, end, " ".join(m.group(0).split())
        return None

    hit = (from_range(unbreak(scope_statement), False) if scope_statement else None) or None
    if hit:
        return _result(*hit[:2], "stated", hit[2])
    if m := YEAR_TO.search(full):
        end = _parse(m["b"])
        if end:  # only the end is stated; the start is left empty rather than guessed
            return {"startDate": None, "endDate": end.isoformat(), "basis": "only the end date is stated", "text": " ".join(m.group(0).split())}
    if hit := from_range(full, True):
        return _result(*hit[:2], "stated", hit[2])
    return {"startDate": None, "endDate": None, "basis": "not stated in the report", "text": None}


def _result(start: date, end: date, basis: str, text: str | None) -> dict:
    return {"startDate": start.isoformat(), "endDate": end.isoformat(), "basis": basis, "text": text}
