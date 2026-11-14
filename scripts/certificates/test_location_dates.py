from datetime import date

import pytest

from dates import report_dates
from location import detect_location
from summary import summarize


def loc(texts, url=None, company=None, short=None):
    r = detect_location(url, texts, company, short)
    return r["city"], r["country"]


def test_uk_address_skips_county_lines():
    page = "Castings P.L.C.\nLichfield Road\nBrownhills\nWest Midlands\nWS8 6JZ"
    assert loc(["intro", page]) == ("Brownhills", "United Kingdom")


def test_uk_postcode_on_the_city_line():
    assert loc(["x", "please contact us:\nPoole BH12 4NJ"]) == ("Poole", "United Kingdom")


def test_italian_address_with_province():
    assert loc(["x", "Via Enrico Fermi, 5\n25030 Adro (BS)\nP.IVA IT00561340985"]) == ("Adro", "Italy")


def test_us_headquarters_sentence():
    text = "WFI employs a staff of 192 at its headquarters in Waupaca, Wisconsin. Our plants employ locally."
    assert loc([text], company="Waupaca Foundry", short="Waupaca Foundry") == ("Waupaca", "United States")


def test_company_name_followed_by_its_seat_and_country_sentence():
    text = "Georg Fischer AG is headquartered in Switzerland and operates in 46 countries. Report of Georg Fischer AG, Schaffhausen and its subsidiaries."
    assert loc([text], company="Georg Fischer AG", short="Georg Fischer") == ("Schaffhausen", "Switzerland")


def test_other_companies_headquarters_are_ignored():
    text = "We sponsored a theater company based in St. Paul, Minnesota."
    assert loc([text], company="Acme", short="Acme")[0] is None


def test_postal_line_uses_vat_prefix_and_web_address_as_fallbacks():
    assert loc(["x", "Hauptstrasse 1\n35260 Stadtallendorf\nVAT No. DE123456789"]) == ("Stadtallendorf", "Germany")
    assert loc(["nothing here"], url="https://www.acme.co.uk/a.pdf") == (None, "United Kingdom")


@pytest.mark.parametrize("text,start,end,basis", [
    ("for the period [April 1, 2024 - March 31, 2025] with reference to GRI", "2024-04-01", "2025-03-31", "stated"),
    ("This statement covers the period from 1 January to 31 De - cember 2024.", "2024-01-01", "2024-12-31", "stated"),
    ("period from 1 July to 30 June 2025", "2024-07-01", "2025-06-30", "stated"),
    ("It is the ESG Report for the year to 31 March 2024.", None, "2024-03-31", "only the end date is stated"),
    ("The year ended 29 February 2024 was strong.", None, "2024-02-29", "only the end date is stated"),
])
def test_dates_only_when_stated(text, start, end, basis):
    r = report_dates([text], None)
    assert (r["startDate"], r["endDate"], r["basis"]) == (start, end, basis)


@pytest.mark.parametrize("text", ["MFG FY2023 results", "2024 Sustainability report", "nothing about dates",
                                  "Delivery slot: 1 May to 31 May 2030 for the new line."])
def test_nothing_is_inferred(text):
    r = report_dates([text], None)
    assert r == {"startDate": None, "endDate": None, "basis": "not stated in the report", "text": None}


def test_summary_keeps_the_reporting_period_text_and_notes_missing_dates():
    doc = {"company": {"name": "Acme Ltd", "confidence": "high", "source": "content+url"}, "author": None,
           "location": {"city": "X", "country": "Y", "countryEvidence": "address"}, "title": "T", "titleSource": "pdf-metadata",
           "scope": {"reportingPeriod": "FY2023"}, "dates": report_dates(["MFG FY2023 results"], None)}
    s = summarize({"kind": "document", "document": doc})
    assert (s["reportingPeriod"], s["startDate"], s["endDate"]) == ("FY2023", None, None)
    assert "start and end date not stated in the report" in s["notes"]
    doc["dates"] = report_dates(["ESG report for the year to 31 March 2024."], None)
    s = summarize({"kind": "document", "document": doc})
    assert (s["startDate"], s["endDate"]) == (None, "2024-03-31") and any("start date not stated" in n for n in s["notes"])


def test_author_or_issuer_prefers_a_real_author_name():
    base = {"company": {"name": "Acme Ltd", "confidence": "high", "source": "content+url"},
            "location": {"city": "X", "country": "Y", "countryEvidence": "address"},
            "dates": {"startDate": "2024-01-01", "endDate": "2024-12-31", "basis": "stated"},
            "title": "T", "titleSource": "pdf-metadata", "scope": {"reportingPeriod": None}}
    person = summarize({"kind": "document", "document": {**base, "author": "Stewart Wren"}})
    assert (person["authorOrIssuer"], person["authorOrIssuerRole"]) == ("Stewart Wren", "author")
    for generic in (None, "", "admin", "Microsoft Office User", "PC"):
        s = summarize({"kind": "document", "document": {**base, "author": generic}})
        assert (s["authorOrIssuer"], s["authorOrIssuerRole"]) == ("Acme Ltd", "issuer")


def test_year_first_financial_year_is_a_reporting_period_without_dates():
    from report import _scope

    s = _scope(["REVENUE FOR THE 2024 FINANCIAL YEAR Substantial contribution criterion"])
    assert s["reportingPeriod"] == "2024 FINANCIAL YEAR"
    assert report_dates(["REVENUE FOR THE 2024 FINANCIAL YEAR"], None)["startDate"] is None
