"""Cases found while extracting the 22-report batch (kept as small synthetic examples)."""
from unittest import mock

import pytest

import fetch
from company import detect_company, host_label
from dates import find_period
from location import detect_location
from report import _clean_title


def loc(text, company="Acme Corporation", short="Acme", url=None):
    r = detect_location(url, text if isinstance(text, list) else [text], company, short)
    return r["city"], r["country"]


def test_head_office_address_skips_the_prefecture_and_takes_the_city():
    assert loc("Corporate Profile Head Office 3-11-8, Sumiyoshi-cho, Anjo, Aichi 446-8502, Japan Phone: +81") == ("Anjo", "Japan")
    assert loc("Company Address Head Office 1 Toyota-cho, Toyota City, Aichi Prefecture, Japan 1-4-18") == ("Toyota City", "Japan")


def test_a_ward_is_replaced_by_its_city():
    assert loc("Head Office 6-1 Marunouchi 2-chome, Chiyoda-ku, Tokyo 100-8071, Japan") == ("Tokyo", "Japan")


def test_participial_headquarters_sentence_may_name_the_company_by_its_abbreviation():
    text = "Headquartered in Irving, Texas, CMC is a publicly traded company."
    assert loc(text, "Commercial Metals Company", "Commercial Metals") == ("Irving", "United States")
    assert loc("Headquartered in Detroit, Michigan, GM is a company.", "General Motors Company", "General Motors") == ("Detroit", "United States")


def test_the_companys_headquarters_are_located_in():
    assert loc("The company's headquarters are located in Uboldo Varese, Italy. More text.") == ("Uboldo Varese", "Italy")


def test_registered_office_with_an_italian_province_code():
    text = "Acciaierie Venete S.p.A., the parent company with registered office in Borgo Valsugana (TN) and administrative headquarters in Camin (PD)"
    assert loc(text, "Acciaierie Venete S.p.A", "Acciaierie Venete") == ("Borgo Valsugana", "Italy")


def test_bare_city_country_mentions_never_pick_a_city():
    text = "Our customers include firms in Munich, Germany and Kunshan, China. Plants in Europe, Mexico."
    assert loc(text) == (None, None)


def test_job_titles_and_divisions_are_not_cities():
    assert loc(["x", "74100 Managing Director, South Korea"])[0] is None
    assert loc("Georg Fischer AG, GM Financial and its subsidiaries", "Georg Fischer AG", "Georg Fischer")[0] is None


def test_other_companies_and_plants_do_not_beat_the_head_office_sentence():
    text = "Our plant is located at 59393 Steenbecque France. The company's headquarters are located in Milan, Italy."
    assert loc(text) == ("Milan", "Italy")


def test_legal_form_gives_a_country_only_as_a_last_resort():
    assert detect_location(None, ["37060 Nogarole Rocca"], "UFI Filters S.p.A", "UFI Filters")["country"] == "Italy"


@pytest.mark.parametrize("url,label", [("https://global.toyota/x.pdf", "toyota"), ("https://esg.cmc.com/x.pdf", "cmc"),
                                       ("https://annualreport2024.volkswagen-group.com/x.pdf", "volkswagengroup"),
                                       ("https://cdn.arcelormittal.com/x.pdf", "arcelormittal")])
def test_generic_subdomains_and_brand_domains(url, label):
    assert host_label(url) == label


def test_an_abbreviation_is_replaced_by_the_name_it_stands_for():
    text = "CMC grew. CMC is global. " * 10 + "Commercial Metals Company (CMC) reported results. Commercial Metals Company is based in Texas."
    assert detect_company("https://esg.cmc.com/x.pdf", [text])["name"] == "Commercial Metals Company"


def test_pdf_author_with_a_legal_form_is_a_strong_candidate():
    text = "Toyota Inc. appears once. " + "Toyota Motor Corporation reported results. " * 3
    assert detect_company("https://global.toyota/x.pdf", [text], "Toyota Motor Corporation")["name"] == "Toyota Motor Corporation"


def test_repeated_first_word_cuts_a_garbled_legal_name():
    text = "ADR Axles USA ADR S.p.A reported. " * 4
    assert "ADR Axles USA" not in (detect_company(None, [text])["name"] or "")  # the abbreviation alone is refused, never the garble
    assert detect_company("https://www.adraxles.com/x.pdf", [text])["name"] == "ADR Axles"


def test_exact_domain_name_beats_a_longer_unsuffixed_name():
    text = "Baettr is a group. Baettr Tianjin is a plant. " * 6
    assert detect_company("https://baettr.com/x.pdf", [text])["name"] == "Baettr"


@pytest.mark.parametrize("raw,clean", [("- 1 -                       Environmental Report 2024", "Environmental Report 2024"),
                                       ("2024 2024 Sustainability Report", "2024 Sustainability Report"),
                                       ("Sustainability Report © 2025 Kaiser Aluminum", "Sustainability Report")])
def test_title_cleaning(raw, clean):
    assert _clean_title(raw) == clean


def test_period_candidates_that_do_not_fit_the_report_year_are_ignored():
    text = "Targets for FY2030. Data for January 1, 2021 to March 31, 2022. This report covers April 1, 2022 to March 31, 2023."
    p = find_period([text], None, 2023)
    assert (p["periodText"], p["startDate"], p["endDate"]) == ("April 1, 2022 to March 31, 2023", "2022-04-01", "2023-03-31")
    assert find_period(["Targets for FY2030."], None, 2024)["periodText"] is None


def test_an_encoded_colon_is_retried_once_with_a_plain_colon():
    calls = []

    def fake_get(self, url, **kwargs):
        calls.append(url)
        resp = mock.MagicMock(is_redirect=False, status_code=400 if "%3A" in url else 200, headers={"Content-Type": "application/pdf"})
        resp.iter_content = lambda n: iter([b"%PDF-1.4 x"])
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda *a: None
        resp.close = lambda: None
        return resp

    import tempfile
    with mock.patch("fetch.requests.Session.get", fake_get), mock.patch("fetch.check_url"), tempfile.TemporaryDirectory() as d:
        path, info = fetch.download("https://assets.example.com/api/uuid%3Aabc/x.pdf", d)
    assert calls == ["https://assets.example.com/api/uuid%3Aabc/x.pdf", "https://assets.example.com/api/uuid:abc/x.pdf"]
    assert info["finalUrl"].endswith("uuid:abc/x.pdf")
