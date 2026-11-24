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
    "Ireland": ["Ireland"], "Luxembourg": ["Grand Duchy of Luxembourg", "Luxembourg"], "Turkey": ["Turkey", "Türkiye"],
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
POSTAL_LINE = re.compile(r"^(?:[A-Z]{1,2}-)?(\d{4,5})\s+([A-Z][^\W\d_][\w'’. -]{2,28})$")  # "35260 Stadtallendorf", "L-1160 Luxembourg"
HQ = re.compile(
    r"(?i:headquarter(?:s|ed)|head ?office|registered office|principal office)\s+(?:(?i:is|are)\s+)?(?:(?i:located|situated|based)\s+)?(?i:in)\s+"
    r"(?:the\s+(?:city|town)\s+of\s+)?([A-Z][\w.'’ -]{1,30}?)(?:\s*\(([A-Z]{2})\))?(?:,\s*([A-Z][\w.'’ -]{1,30}?))?"
    r"(?=[.;,)]|\s+(?:and|with|where|is|has|which|since|that|in|at)\b|$)"
)
OFFICE_LABEL = re.compile(r"(?i:head\s*offi\s?ce|headquarters|registered office|corporate (?:office|address)|company address)")
NOT_A_CITY = re.compile(r"report|statement|sustainab|annual|contents|chapter|page|table|figure", re.I)
BAD_CITY = re.compile(
    r"\b(offices?|headquarters?|campus|plants?|centre|center|department|division|financial|corporation|company|group|holdings?|"
    r"motors?|industries|limited|ltd|inc|gmbh|plc|factory|facility|facilities|site|region|europe|asia|america|africa|pacific|"
    r"international|global|north|south|east|west|director|officer|president|manager|chairman|chief|ceo|cfo|vice|executive|"
    r"representative|secretary|member|board|established)\b|\d",
    re.I,
)
REGION_SEGMENT = re.compile(r"prefecture|province|state|county|region|district|\d", re.I)


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


CITY_STATES = {"Luxembourg", "Singapore"}


def _clean_city(text: str) -> str | None:
    text = re.sub(r"\s+", " ", text).strip(" ,.-|")
    text = re.sub(r"^[A-Z]{2}\s+(?=[A-Z])", "", text)  # Dutch postcodes are "2132 LS Hoofddorp": the letters are not the city
    if not text or len(text) > 32 or NOT_A_CITY.search(text) or BAD_CITY.search(text):
        return None
    if country_of(text) and country_of(text) not in CITY_STATES:
        return None
    return text


def _country_at_start(segment: str) -> str | None:
    low = segment.strip(" .").lower()
    for alias in sorted(ALIAS, key=len, reverse=True):
        if low.startswith(alias) and not low[len(alias):len(alias) + 1].isalpha():
            return ALIAS[alias]
    return None


def _office_address(flat: str) -> tuple[str | None, str | None]:
    """'Head Office 3-11-8, Sumiyoshi-cho, Anjo, Aichi 446-8502, Japan' -> ('Anjo', 'Japan')."""
    for m in OFFICE_LABEL.finditer(flat):
        segments = [s.strip() for s in flat[m.end(): m.end() + 170].split(",")]
        for i, segment in enumerate(segments):
            country = _country_at_start(segment)
            if country and i >= 2:
                for back in range(i - 1, 0, -1):  # skip the prefecture / state / postcode, take the place before it
                    seg = segments[back]
                    if REGION_SEGMENT.search(seg) and not re.search(r"\bcity\b", seg, re.I) or seg.lower() in US_STATES:
                        continue
                    city = _clean_city(seg.split(" Head")[-1]) or (_clean_city(re.sub(r"\bCity\b", "", seg)) and seg.strip())
                    if city and re.search(r"-(?:ku|cho|machi|gun)$", city, re.I) and back + 1 < i:
                        city = _clean_city(re.sub(r"[\d-]+", "", segments[back + 1])) or city  # "Chiyoda-ku, Tokyo 100-8071" -> Tokyo
                    if city:
                        return city, country
                    break
            if country:
                break
    return None, None


def detect_location(url: str | None, texts: list[str], company: str | None = None, short_name: str | None = None, debug: bool = False):
    """The company's base. Only addresses and sentences about the company itself count; a bare "City, Country" mention
    (a plant, a customer, a supplier) is never used to pick a city. City and country come from the same piece of evidence."""
    found: list[tuple[int, str | None, str | None, str]] = []  # (strength, city, country, evidence)
    names = [n for n in (company, short_name) if n and len(n) > 2]
    for full in {n for n in (company, short_name) if n}:  # "Commercial Metals Company" -> "CMC", "Commercial Metals" -> "CM"
        words = [w for w in full.split() if w[0].isalpha()]
        stripped = [w for w in words if not re.fullmatch(r"(?:" + "|".join(["Company", "Corporation", "Corp\\.?", "Inc\\.?", "Ltd\\.?", "Limited", "AG", "SE", "PLC", "N\\.V\\.?", "S\\.p\\.A\\.?", "A/S", "ASA", "GmbH"]) + ")", w, re.I)]
        for group in (words, stripped):
            if len(group) >= 2 and 2 <= len(group) <= 5:
                names.append("".join(w[0].upper() for w in group))
    name_rx = re.compile("|".join(re.escape(n) for n in names), re.I) if names else None
    pages = [[l.strip() for l in t.splitlines() if l.strip()] for t in texts]
    edge = list(dict.fromkeys(list(range(min(2, len(pages)))) + list(range(max(2, len(pages) - 4), len(pages)))))

    def near_name(lines: list[str], i: int) -> int:
        return 2 if name_rx and name_rx.search(" ".join(lines[max(0, i - 5): i + 1])) else 0

    for p in edge:  # opening and closing pages, where contact details live
        lines = pages[p]
        for i, line in enumerate(lines):
            bonus = near_name(lines, i)
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
                    found.append((5 + bonus, city, "United Kingdom", "address (UK postcode)"))
            elif m := ITALY.search(line):
                if city := _clean_city(m.group(1)):
                    found.append((5 + bonus, city, "Italy", "address (postcode + province)"))
            elif m := US_ZIP.search(line):
                if city := _clean_city(m.group(1)):
                    found.append((5 + bonus, city, "United States", "address (city, state ZIP)"))
            elif (m := POSTAL_LINE.match(line)) and not re.match(r"(19|20)\d\d$", m.group(1)):
                around = lines[max(0, i - 3): i + 4]
                country = next((country_of(x) for x in around if country_of(x)), None)
                vat = re.search(r"\b(?:VAT|P\.?\s?IVA|USt\.?-?Id\w*)\s*(?:No\.?|Nr\.?)?:?\s*([A-Z]{2})\d", " ".join(around))
                if city := _clean_city(m.group(2)):
                    found.append((4 + bonus, city, country or (VAT_PREFIX.get(vat.group(1)) if vat else None), "address (postcode + city)"))

    flat = " ".join(" ".join(texts).split())
    edge_flat = " ".join(" ".join(texts[p] for p in edge).split())
    country_rx = "|".join(re.escape(a) for a in sorted(ALIAS, key=len, reverse=True))
    inline = re.compile(rf"\b\d{{4,6}}\s+([A-Z][^\W\d_][\w'’.-]*(?:\s[A-Z][\w'’.-]*){{0,2}}),?\s+({country_rx})\b", re.I)
    for m in inline.finditer(edge_flat):  # "... Via Pasolini 74 20151 Milano Italy"
        city = _clean_city(m.group(1))
        if city and country_of(m.group(2)):
            near = 2 if name_rx and name_rx.search(edge_flat[max(0, m.start() - 160): m.start()]) else 0
            found.append((4 + near, city, country_of(m.group(2)), "address (postcode + city + country)"))

    city, country = _office_address(flat)
    if city:
        found.append((6, city, country, "head office address"))

    pronoun = re.compile(r"\b(?:our|its|the company['’]s|the group['’]s|the company|the group)\s+(?:[\w-]+\s+){0,2}$", re.I)
    for m in HQ.finditer(flat):
        before, after = flat[max(0, m.start() - 120): m.start()], flat[m.end(): m.end() + 80]
        about_us = bool(
            (name_rx and name_rx.search(before)) or pronoun.search(before)
            or (name_rx and flat[m.start(): m.start() + 12].lower() == "headquartere" and name_rx.search(after))  # "Headquartered in Detroit, GM is ..."
        )
        if not about_us:
            continue  # "a theatre company based in St. Paul" is not about the reporting company
        second = m.group(3)
        city, country = _classify(m.group(1), second)
        if city and re.search(r"-(?:ku|cho|machi|gun)$", city, re.I):
            continue  # a district or neighbourhood, not the city
        if m.group(2) and not country:
            country = "Italy"  # "Borgo Valsugana (TN)": an Italian province code
        if city and (not _clean_city(city) or len(city) < 3):
            continue
        found.append((7 if city else 6, city, country, "headquarters sentence"))
    for name in [company] if company and company != short_name else []:  # "Georg Fischer AG, Schaffhausen and its consolidated subsidiaries"
        for m in re.finditer(re.escape(name) + r",\s+([A-Z][^\W\d_][\w'’ -]{2,24}?)(?=\s+(?:and|is|has|was)\b|[.;,)])", flat):
            if c := _clean_city(m.group(1)):
                found.append((5, c, None, "company name followed by its seat"))

    # a city without a country may borrow one from a "City, Country" mention, but such a mention never chooses a city
    pair_country = {}
    for m in re.finditer(r"\b([A-Z][a-zäöüéè'’-]+(?: [A-Z][a-zäöüéè'’-]+)?),\s+([A-Z][A-Za-z .]+?)(?=[\s.,;)]|$)", flat):
        c, k = _classify(m.group(1), m.group(2))
        if c and k:
            pair_country.setdefault(c, k)

    if debug:
        return sorted(found, key=lambda f: -f[0])

    form = re.search(r"\b(S\.?p\.?A\.?|S\.?r\.?l\.?|Oyj|ASA|A/S|AB|PLC|plc)\W*$", company or "")
    form_country = {"spa": "Italy", "srl": "Italy", "oyj": "Finland", "asa": "Norway", "a/s": "Denmark", "ab": "Sweden", "plc": "United Kingdom"}.get(
        re.sub(r"[^a-z/]", "", form.group(1).lower()) if form else "")
    host = (urlsplit(url or "").hostname or "").lower().split(".")
    tld_country = TLD.get(host[-1]) if len(host) > 1 else None
    vat = re.search(r"\b(?:VAT|P\.?\s?IVA|USt\.?-?Id\w*)\s*(?:No\.?|Nr\.?)?:?\s*([A-Z]{2})\d", flat)
    vat_country = VAT_PREFIX.get(vat.group(1)) if vat else None

    groups: dict[tuple[str, str | None], tuple[int, str]] = {}
    for strength, c, k, why in found:
        if c and strength > groups.get((c, k), (0, ""))[0]:
            groups[(c, k)] = (strength, why)
    best_city = max(groups.items(), key=lambda kv: kv[1][0], default=None)  # first of equals wins: earlier evidence
    country_only = Counter()
    for strength, c, k, why in found:
        if k and not c:
            country_only[(k, why)] += strength

    if best_city:
        (city, country), (_, why) = best_city
        country_why = why
        if not country:
            country = pair_country.get(city)
            country_why = "'City, Country' mention" if country else None
        if not country and country_only:
            (country, country_why), _ = country_only.most_common(1)[0]
        country = country or vat_country or form_country or tld_country
        return {"city": city, "cityEvidence": why, "country": country,
                "countryEvidence": country_why or ("VAT number prefix" if country == vat_country else "legal form of the company name"
                                                   if country == form_country else "web address ending" if country else None)}
    if country_only:
        (country, why), _ = country_only.most_common(1)[0]
        return {"city": None, "cityEvidence": None, "country": country, "countryEvidence": why}
    country = vat_country or form_country or tld_country
    return {"city": None, "cityEvidence": None, "country": country,
            "countryEvidence": "VAT number prefix" if country == vat_country else "legal form of the company name"
                               if country == form_country else "web address ending" if country else None}
