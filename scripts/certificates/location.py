"""Where the company is based (country and city), from address blocks and 'headquartered in ...' sentences."""
import re
from collections import Counter
from urllib.parse import urlsplit

COUNTRIES = {
    "United Kingdom": ["United Kingdom", "UK", "U.K.", "Great Britain", "England", "Scotland", "Wales"],
    "United States": ["United States of America", "United States", "USA", "U.S.A.", "U.S."],
    "Germany": ["Germany", "Deutschland"], "Switzerland": ["Switzerland", "Schweiz", "Suisse", "Svizzera"],
    "Italy": ["Italy", "Italia"], "France": ["France"], "Spain": ["Spain", "España"], "Portugal": ["Portugal"],
    "Netherlands": ["Netherlands", "The Netherlands", "Nederland"], "Belgium": ["Belgium", "België"],
    "Austria": ["Austria", "Österreich"], "Sweden": ["Sweden", "Sverige"], "Norway": ["Norway", "Norge"],
    "Denmark": ["Denmark", "Danmark"], "Finland": ["Finland", "Suomi"], "Poland": ["Poland", "Polska"],
    "Czech Republic": ["Czech Republic", "Czechia"], "Slovakia": ["Slovakia"], "Hungary": ["Hungary"],
    "Romania": ["Romania"], "Slovenia": ["Slovenia"], "Croatia": ["Croatia"], "Greece": ["Greece"],
    "Ireland": ["Ireland"], "Luxembourg": ["Luxembourg"], "Turkey": ["Turkey", "Türkiye"],
    "Canada": ["Canada"], "Mexico": ["Mexico"], "Brazil": ["Brazil", "Brasil"], "India": ["India"],
    "China": ["China"], "Japan": ["Japan"], "South Korea": ["South Korea", "Korea"], "Taiwan": ["Taiwan"],
    "Singapore": ["Singapore"], "Australia": ["Australia"], "South Africa": ["South Africa"],
}
ALIAS = {a.lower(): c for c, names in COUNTRIES.items() for a in names}
US_STATES = {s.lower() for s in (
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois Indiana "
    "Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri Montana Nebraska "
    "Nevada Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah Vermont Virginia Washington Wisconsin Wyoming "
    "New-Hampshire New-Jersey New-Mexico New-York North-Carolina North-Dakota Rhode-Island South-Carolina South-Dakota "
    "West-Virginia").replace("-", " ").split(" ") if s} | {"new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "rhode island", "south carolina", "south dakota", "west virginia"}
TLD = {"uk": "United Kingdom", "it": "Italy", "de": "Germany", "ch": "Switzerland", "fr": "France", "es": "Spain",
       "nl": "Netherlands", "be": "Belgium", "at": "Austria", "se": "Sweden", "no": "Norway", "dk": "Denmark",
       "fi": "Finland", "pl": "Poland", "ie": "Ireland", "pt": "Portugal", "cz": "Czech Republic", "us": "United States",
       "ca": "Canada", "jp": "Japan", "cn": "China", "in": "India", "br": "Brazil", "mx": "Mexico", "au": "Australia"}
VAT_PREFIX = {"IT": "Italy", "DE": "Germany", "FR": "France", "ES": "Spain", "NL": "Netherlands", "BE": "Belgium",
              "AT": "Austria", "SE": "Sweden", "DK": "Denmark", "FI": "Finland", "PL": "Poland", "GB": "United Kingdom",
              "IE": "Ireland", "PT": "Portugal", "CH": "Switzerland"}
UK_COUNTIES = {"west midlands", "east midlands", "staffordshire", "warwickshire", "worcestershire", "shropshire", "dorset",
               "lancashire", "yorkshire", "west yorkshire", "south yorkshire", "north yorkshire", "derbyshire", "nottinghamshire",
               "lincolnshire", "leicestershire", "cheshire", "merseyside", "greater manchester", "kent", "essex", "surrey", "sussex",
               "hampshire", "devon", "cornwall", "somerset", "norfolk", "suffolk", "cambridgeshire", "hertfordshire", "oxfordshire",
               "berkshire", "buckinghamshire", "gloucestershire", "durham", "cumbria", "northumberland", "united kingdom", "england"}
STREET = re.compile(r"\d|\b(road|street|lane|avenue|drive|way|close|park|estate|via|strasse|straße)\b", re.I)
UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s?(\d[A-Z]{2})\b")
ITALY = re.compile(r"\b\d{5}\s+([A-Z][\w'’ -]{1,30}?)\s*\(([A-Z]{2})\)")
US_ZIP = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?),?\s+([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")
POSTAL_LINE = re.compile(r"^(\d{4,5})\s+([A-Z][^\W\d_][\w'’. -]{2,28})$")
HQ = re.compile(
    r"(?:headquarter(?:s|ed)|head ?office|registered office|principal office|based)\s+(?:is\s+)?(?:located\s+)?in\s+"
    r"(?:the\s+(?:city|town)\s+of\s+)?([A-Z][\w.'’ -]{1,30}?)(?:,\s*([A-Z][\w.'’ -]{1,30}?))?"
    r"(?=[.;,)]|\s+(?:and|with|where|is|has|which|since|that|in)\b)"
)
NOT_A_CITY = re.compile(r"report|statement|sustainab|annual|contents|chapter|page|table|figure", re.I)


def country_of(token: str | None) -> str | None:
    return ALIAS.get((token or "").strip().rstrip(".").lower()) or ALIAS.get((token or "").strip().lower())


def _classify(first: str, second: str | None) -> tuple[str | None, str | None]:
    """'Waupaca, Wisconsin' -> (city, country); 'Switzerland' -> (None, country)."""
    if country_of(first):
        return None, country_of(first)
    if second and country_of(second):
        return first.strip(), country_of(second)
    if second and second.strip().lower() in US_STATES:
        return first.strip(), "United States"
    return first.strip(), None


def _clean_city(text: str) -> str | None:
    text = re.sub(r"\s+", " ", text).strip(" ,.-|")
    return text if text and not NOT_A_CITY.search(text) and len(text) <= 32 else None


def detect_location(url: str | None, texts: list[str], company: str | None = None, short_name: str | None = None) -> dict:
    # (strength, city, country, evidence): the strongest evidence wins; ties go to the most frequent city
    found: list[tuple[int, str | None, str | None, str]] = []
    pages = [[l.strip() for l in t.splitlines() if l.strip()] for t in texts]
    edge = list(range(min(2, len(pages)))) + list(range(max(2, len(pages) - 4), len(pages)))

    for p in dict.fromkeys(edge):  # opening and closing pages, where contact details live
        lines = pages[p]
        for i, line in enumerate(lines):
            if m := UK_POSTCODE.search(line):
                before = line[: m.start()]
                city = _clean_city(re.split(r"[|,]", before)[-1]) if before.strip(" ,|") else None
                k = i - 1
                while city is None and k >= max(0, i - 4):
                    cand = lines[k]
                    if cand.lower() not in UK_COUNTIES and not STREET.search(cand):
                        city = _clean_city(cand)
                    k -= 1
                if city:
                    found.append((5, city, "United Kingdom", "address (UK postcode)"))
            elif m := ITALY.search(line):
                found.append((5, _clean_city(m.group(1)), "Italy", "address (postcode + province)"))
            elif m := US_ZIP.search(line):
                found.append((5, _clean_city(m.group(1)), "United States", "address (city, state ZIP)"))
            elif (m := POSTAL_LINE.match(line)) and not re.match(r"(19|20)\\d\\d$", m.group(1)):
                country = next((country_of(x) for x in lines[max(0, i - 3): i + 4] if country_of(x)), None)
                vat = re.search(r"\b(?:VAT|P\.?\s?IVA|USt\.?-?Id\w*)\s*(?:No\.?|Nr\.?)?:?\s*([A-Z]{2})\d", " ".join(lines[max(0, i - 3): i + 4]))
                found.append((4, _clean_city(m.group(2)), country or (VAT_PREFIX.get(vat.group(1)) if vat else None),
                              "address (postcode + city)"))

    flat = " ".join(" ".join(texts).split())
    names = [n for n in (company, short_name) if n]
    about_us = re.compile("|".join([re.escape(n) for n in names] + [r"\b(?:our|its|we|the group|the company)\b"]), re.I)
    for m in HQ.finditer(flat):
        if not about_us.search(flat[max(0, m.start() - 90): m.start()]):
            continue  # "a theatre company based in St. Paul" is not about the reporting company
        city, country = _classify(m.group(1), m.group(2))
        if city and (NOT_A_CITY.search(city) or len(city) < 3):
            continue
        found.append((6, city, country, "headquarters sentence"))
    for name in names:  # "Georg Fischer AG, Schaffhausen and its consolidated subsidiaries"
        for m in re.finditer(re.escape(name) + r",\s+([A-Z][^\W\d_][\w'’ -]{2,24}?)(?=\s+(?:and|is|has|was)\b|[.;,)])", flat):
            if (c := _clean_city(m.group(1))) and not country_of(c):
                found.append((5, c, None, "company name followed by its seat"))
    pair = Counter()
    for m in re.finditer(r"\b(?:in|at)\s+([A-Z][a-zäöüéè'’-]+(?: [A-Z][a-zäöüéè'’-]+)?),\s+([A-Z][A-Za-z .]+?)(?=[\s.,;)]|$)", flat):
        city, country = _classify(m.group(1), m.group(2))
        if city and country:
            pair[(city, country)] += 1
    for (city, country), n in pair.items():
        found.append((1 + min(n, 3) * 0, city, country, f"mentioned {n}x as '{city}, {country}'"))

    host = (urlsplit(url or "").hostname or "").lower().split(".")
    tld_country = TLD.get(host[-1]) if len(host) > 1 else None
    vat = re.search(r"\b(?:VAT|P\.?\s?IVA|USt\.?-?Id\w*)\s*(?:No\.?|Nr\.?)?:?\s*([A-Z]{2})\d", flat)
    vat_country = VAT_PREFIX.get(vat.group(1)) if vat else None

    city_votes, country_votes = Counter(), Counter()
    evidence = {}
    for strength, city, country, why in found:
        if city:
            city_votes[city] += strength
            evidence.setdefault(("city", city), why)
        if country:
            country_votes[country] += strength
            evidence.setdefault(("country", country), why)
    city = city_votes.most_common(1)[0][0] if city_votes else None
    country = country_votes.most_common(1)[0][0] if country_votes else (vat_country or tld_country)
    country_why = evidence.get(("country", country)) or ("VAT number prefix" if country == vat_country else "web address ending")
    return {
        "city": city, "cityEvidence": evidence.get(("city", city)),
        "country": country, "countryEvidence": country_why if country else None,
    }
