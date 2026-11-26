from datetime import date

import pytest

from dates import find_period, report_dates
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


@pytest.mark.parametrize("text,year,start,end,basis", [
    # a full range, in the formats the real reports use
    ("This report covers the period [April 1, 2024 - March 31, 2025] with reference to GRI", 2024, "2024-04-01", "2025-03-31", "stated"),
    ("This statement encompasses the period from 1 January to 31 De - cember 2024.", 2024, "2024-01-01", "2024-12-31", "stated"),
    ("Unless otherwise stated, all information and key figures pertain to the Group for the period from January 1, 2024, to December 31, 2024.",
     2024, "2024-01-01", "2024-12-31", "stated"),
    ("2-3 Reporting period: 01.01.2024 to 31.12.2024; reporting frequency: annual", 2024, "2024-01-01", "2024-12-31", "stated"),
    ("This report is based on activities in FYE 2024 (April 1, 2023, to March 31, 2024).", 2024, "2023-04-01", "2024-03-31", "stated"),
    ("Nissan has prepared this report in accordance with the GRI Standards for the period April 1, 2023 through March 31, 2024.",
     2024, "2023-04-01", "2024-03-31", "stated"),
    ("This report covers the period from 1 July to 30 June 2025", 2025, "2024-07-01", "2025-06-30", "stated"),
    ("Unless otherwise noted, our report includes information from January 1, 2024, through and as of December 31, 2024.",
     2024, "2024-01-01", "2024-12-31", "stated"),
    ("This report covers 1 April 2023 up to and including 31 March 2024.", 2024, "2023-04-01", "2024-03-31", "stated"),
    # whole months
    ("Period covered The period covered in the report is fiscal 2022 (from April 2022 to March 2023).", 2023, "2022-04-01", "2023-03-31", "stated (whole months)"),
    # only a year end is stated: an end date and no start date
    ("It is the ESG Report for the year to 31 March 2024.", 2024, None, "2024-03-31", "only the end date is stated"),
    ("This report covers the year ended 29 February 2024.", 2024, None, "2024-02-29", "only the end date is stated"),
    # the calendar year is January to December by definition
    ("the scope (reporting period) of the Sustainability Report covers information and data for the year 2024 \u2014 which coincides with the "
     "calendar year \u2014 for all segments", 2024, "2024-01-01", "2024-12-31", "stated (calendar year)"),
])
def test_dates_the_report_states(text, year, start, end, basis):
    r = report_dates([text], None, year)
    assert (r["startDate"], r["endDate"]) == (start, end) and r["basis"].startswith(basis)


def test_a_stated_year_end_gives_no_start_date_unless_deriving_is_switched_on():
    text = "It is the ESG Report for the year to 31 March 2024."
    off = find_period([text], None, 2024)
    assert (off["periodText"], off["startDate"], off["endDate"]) == ("year to 31 March 2024", None, "2024-03-31")
    on = find_period([text], None, 2024, derive_start=True)
    assert (on["startDate"], on["endDate"]) == ("2023-04-01", "2024-03-31") and "assumption" in on["basis"]
    leap = find_period(["This report covers the year ended 29 February 2024."], None, 2024, derive_start=True)
    assert (leap["startDate"], leap["endDate"]) == ("2023-03-01", "2024-02-29")


def test_a_range_about_something_else_is_not_the_reporting_period():
    cnh = ("Survey of leave taken covering the period from November 1, 2023, to October 31, 2024. "
           "Unless otherwise stated, the scope (reporting period) of the Sustainability Report covers information and data for the year 2024 "
           "\u2014 which coincides with the calendar year \u2014 for all CNH segments.")
    p = find_period([cnh], None, 2024)
    assert (p["periodText"], p["startDate"], p["endDate"]) == ("calendar year 2024", "2024-01-01", "2024-12-31")
    nippon = "As Ovako has changed its fiscal year end, Ovako\u2019s fiscal 2021 results cover a period from January 1, 2021 to March 31, 2022 (15 months)."
    assert find_period([nippon], None, 2023)["startDate"] is None
    assert find_period(["Delivery slot: 1 May to 31 May 2030 for the new line."], None, 2024)["startDate"] is None


def test_a_typo_in_the_report_does_not_beat_the_stated_period():
    waupaca = ("This report describes our activities during our 2024 fiscal year, covering the time period from April 1, 2024 through March 31, 2024. "
               "WFI has reported the information cited in this GRI content index for the period [April 1, 2024 - March 31, 2025] with reference to GRI.")
    p = find_period([waupaca], None, 2024)
    assert (p["startDate"], p["endDate"]) == ("2024-04-01", "2025-03-31")


@pytest.mark.parametrize("text", ["MFG FY2023 results", "2024 Sustainability report", "nothing about dates",
                                  "Delivery slot: 1 May to 31 May 2030 for the new line."])
def test_nothing_is_inferred(text):
    r = report_dates([text], None)
    assert r == {"startDate": None, "endDate": None, "basis": "not stated in the report", "text": None}


def _doc(dates, period=None):
    return {"company": {"name": "Acme Ltd", "confidence": "high", "source": "content+url"}, "author": "Someone",
            "location": {"city": "X", "country": "Y", "countryEvidence": "address"}, "title": "T", "titleSource": "pdf-metadata",
            "scope": {"reportingPeriod": period}, "dates": dates}


def test_summary_notes_say_exactly_how_each_kind_of_date_was_obtained():
    s = summarize({"kind": "document", "document": _doc(report_dates(["MFG FY2023 results"], None), "FY2023")})
    assert (s["reportingPeriod"], s["startDate"], s["endDate"]) == ("FY2023", None, None)
    assert "start and end date not stated in the report" in s["notes"]

    year_end = "This is the ESG Report for the year to 31 March 2024."
    s = summarize({"kind": "document", "document": _doc(report_dates([year_end], None, 2024), "year to 31 March 2024")})
    assert (s["startDate"], s["endDate"]) == (None, "2024-03-31") and any("start date not stated" in n for n in s["notes"])
    s = summarize({"kind": "document", "document": _doc(report_dates([year_end], None, 2024, derive_start=True))})
    assert (s["startDate"], s["endDate"]) == ("2023-04-01", "2024-03-31") and any("derived (assumption)" in n for n in s["notes"])

    s = summarize({"kind": "document", "document": _doc(report_dates(["This report covers the calendar year 2024."], None, 2024))})
    assert (s["startDate"], s["endDate"]) == ("2024-01-01", "2024-12-31") and any("calendar year the report names" in n for n in s["notes"])
    s = summarize({"kind": "document", "document": _doc(report_dates(["The period covered in the report is (from April 2022 to March 2023)."], None, 2023))})
    assert (s["startDate"], s["endDate"]) == ("2022-04-01", "2023-03-31") and any("first and last day of the months" in n for n in s["notes"])
    s = summarize({"kind": "document", "document": _doc(report_dates(["This report covers the period from 1 January to 31 December 2024."], None, 2024))})
    assert s["notes"] == [] or not any("assumption" in n for n in s["notes"])  # a full range needs no caveat


def test_the_pdf_author_field_is_never_used():
    base = {"company": {"name": "MAT Foundry Group Limited", "confidence": "high", "source": "content+url"},
            "location": {"city": "X", "country": "Y", "countryEvidence": "address"},
            "dates": {"startDate": "2024-01-01", "endDate": "2024-12-31", "basis": "stated"},
            "title": "T", "titleSource": "first-page-heading", "scope": {"reportingPeriod": None}}
    for author in ("Stewart Wren", None, "", "admin", "Microsoft Office User"):
        s = summarize({"kind": "document", "document": {**base, "author": author}})
        assert (s["authorOrIssuer"], s["authorOrIssuerRole"]) == ("MAT Foundry Group Limited", "issuer")
        assert not any("author" in n for n in s["notes"])
