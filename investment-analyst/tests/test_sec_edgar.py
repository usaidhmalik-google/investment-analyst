"""SEC EDGAR adapter: CIK lookup, filing index, HTML→text, section extraction, 8-K items, XBRL facts."""

from __future__ import annotations

import httpx
import pytest

from analyst.config import get_settings
from analyst.data import sec_edgar
from analyst.data.http import MinIntervalLimiter

CIK = "0001045810"
TICKERS = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
    "2": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
}
SUBMISSIONS = {
    "name": "NVIDIA CORP",
    "filings": {
        "recent": {
            "form": ["8-K", "10-Q", "4", "10-K", "10-Q", "8-K"],
            "accessionNumber": [
                "0001045810-26-000020",
                "0001045810-26-000015",
                "0001045810-26-000014",
                "0001045810-26-000012",
                "0001045810-25-000090",
                "0001045810-25-000080",
            ],
            "filingDate": ["2026-08-28", "2026-08-27", "2026-06-01", "2026-02-21", "2025-11-20", "2025-11-19"],
            "reportDate": ["2026-08-28", "2026-07-27", "", "2026-01-25", "2025-10-26", "2025-11-19"],
            "primaryDocument": [
                "nvda-8k.htm",
                "nvda-10q.htm",
                "form4.xml",
                "nvda-10k.htm",
                "nvda-10q-old.htm",
                "nvda-8k-old.htm",
            ],
            "primaryDocDescription": ["8-K", "10-Q", "", "10-K", "10-Q", "8-K"],
        }
    },
}

FILLER = "Our business is subject to many risks including competition, supply constraints and regulation. "


def ten_k_html() -> str:
    toc = (
        "<p>TABLE OF CONTENTS</p>"
        "<p>Item 1. Business 4</p><p>Item 1A. Risk Factors 12</p><p>Item 1B. Unresolved Staff Comments 30</p>"
        "<p>Item 7. Management&#8217;s Discussion and Analysis 40</p><p>Item 8. Financial Statements 50</p>"
    )
    body = (
        f"<h2>Item 1. Business</h2><p>{FILLER * 8}</p>"
        f"<h2>Item 1A. Risk Factors</h2><p>RISK BODY START. {FILLER * 30} RISK BODY END.</p>"
        "<h2>Item 1B. Unresolved Staff Comments</h2><p>None.</p>"
        f"<h2>Item 7. Management's Discussion and Analysis</h2><p>{FILLER * 10}</p>"
        "<h2>Item 8. Financial Statements</h2><p>See below.</p>"
    )
    return f"<html><head><title>10-K</title><style>.x{{}}</style></head><body>{toc}{body}</body></html>"


def ten_q_text() -> str:
    toc = (
        "PART I - FINANCIAL INFORMATION\nItem 1. Financial Statements 3\n"
        "Item 2. Management's Discussion and Analysis of Financial Condition 20\n"
        "Item 3. Quantitative and Qualitative Disclosures About Market Risk 30\nItem 4. Controls and Procedures 31\n"
        "PART II - OTHER INFORMATION\nItem 1. Legal Proceedings 32\nItem 1A. Risk Factors 33\n"
    )
    body = (
        f"\nItem 1. Financial Statements\n{FILLER * 6}\n"
        f"\nItem 2. Management's Discussion and Analysis of Financial Condition\nMDNA START. {FILLER * 20} MDNA END.\n"
        f"\nItem 3. Quantitative and Qualitative Disclosures About Market Risk\n{FILLER * 5}\n"
        "\nItem 4. Controls and Procedures\nEffective.\n"
    )
    return toc + body


@pytest.fixture
def sec(mock_http):
    mock_http.get(sec_edgar.TICKER_MAP_URL).mock(return_value=httpx.Response(200, json=TICKERS))
    mock_http.get(sec_edgar.SUBMISSIONS_URL.format(cik=CIK)).mock(return_value=httpx.Response(200, json=SUBMISSIONS))
    return mock_http


def archive(document: str, accession: str = "000104581026000012") -> str:
    return f"https://www.sec.gov/Archives/edgar/data/1045810/{accession}/{document}"


class TestCikLookup:
    def test_resolve_and_zero_pad(self, sec):
        assert sec_edgar.resolve_cik("nvda") == (CIK, "NVIDIA CORP")
        assert sec_edgar.resolve_cik("AAPL") == ("0000320193", "Apple Inc.")

    def test_dot_class_shares_mapped_to_dash(self, sec):
        assert sec_edgar.resolve_cik("BRK.B") == ("0001067983", "BERKSHIRE HATHAWAY INC")

    def test_unknown_ticker(self, sec):
        with pytest.raises(LookupError, match="not found in SEC EDGAR"):
            sec_edgar.resolve_cik("ZZZZ")

    def test_list_payload_and_caching(self, mock_http):
        route = mock_http.get(sec_edgar.TICKER_MAP_URL).mock(
            return_value=httpx.Response(200, json=[{"cik_str": 1, "ticker": "ONE"}])
        )
        assert sec_edgar.resolve_cik("ONE") == ("0000000001", "")
        sec_edgar.resolve_cik("ONE")
        assert route.call_count == 1

    def test_user_agent_header_sent(self, sec, monkeypatch):
        monkeypatch.setenv("SEC_USER_AGENT", "Test Co test@example.com")
        get_settings.cache_clear()
        sec_edgar.resolve_cik("NVDA")
        request = sec.calls.last.request
        assert request.headers["User-Agent"] == "Test Co test@example.com"


class TestListFilings:
    def test_form_filter_and_url_construction(self, sec):
        listing = sec_edgar.list_filings("nvda", ("10-K", "10-Q"), limit=5)
        assert listing.ticker == "NVDA" and listing.cik == CIK and listing.company_name == "NVIDIA CORP"
        assert [f.form for f in listing.filings] == ["10-Q", "10-K", "10-Q"]
        ten_k = listing.filings[1]
        assert ten_k.accession_number == "0001045810-26-000012"
        assert ten_k.url == archive("nvda-10k.htm")
        assert ten_k.report_date == "2026-01-25" and ten_k.filing_date == "2026-02-21"
        assert ten_k.description == "10-K"
        assert listing.source == "SEC EDGAR"

    def test_limit(self, sec):
        listing = sec_edgar.list_filings("NVDA", ("10-K", "10-Q", "8-K"), limit=2)
        assert [f.form for f in listing.filings] == ["8-K", "10-Q"]

    def test_case_insensitive_forms_and_empty_report_date(self, sec):
        listing = sec_edgar.list_filings("NVDA", ("4",), limit=5)
        assert len(listing.filings) == 1
        assert listing.filings[0].report_date is None and listing.filings[0].description is None

    def test_missing_optional_arrays(self, mock_http):
        mock_http.get(sec_edgar.TICKER_MAP_URL).mock(return_value=httpx.Response(200, json=TICKERS))
        recent = {
            k: v
            for k, v in SUBMISSIONS["filings"]["recent"].items()
            if k not in ("reportDate", "primaryDocDescription")
        }
        mock_http.get(sec_edgar.SUBMISSIONS_URL.format(cik=CIK)).mock(
            return_value=httpx.Response(200, json={"filings": {"recent": recent}})
        )
        listing = sec_edgar.list_filings("NVDA", ("10-K",), limit=5)
        assert listing.company_name == "NVIDIA CORP"  # falls back to the ticker map title
        assert listing.filings[0].report_date is None and listing.filings[0].description is None

    def test_no_filings_block(self, mock_http):
        mock_http.get(sec_edgar.TICKER_MAP_URL).mock(return_value=httpx.Response(200, json=TICKERS))
        mock_http.get(sec_edgar.SUBMISSIONS_URL.format(cik=CIK)).mock(return_value=httpx.Response(200, json={}))
        assert sec_edgar.list_filings("NVDA", ("10-K",), limit=5).filings == []


class TestHtmlToText:
    def test_strips_non_content_and_decodes_entities(self):
        doc = (
            "<html><head><title>T</title><script>var x = 1;</script></head><body>"
            "<ix:header><ix:hidden>dei:Secret 999</ix:hidden></ix:header>"
            "<style>p { color: red }</style>"
            "<div>AT&amp;T&#8217;s&nbsp;results</div><p>Line&nbsp;two</p>"
            "<table><tr><td>Revenue</td><td>$1,000</td></tr></table>"
            "</body></html>"
        )
        text = sec_edgar.html_to_text(doc)
        assert "var x" not in text and "color" not in text and "999" not in text and "T\n" not in text
        assert "AT&T’s results" in text and "Line two" in text
        assert "Revenue$1,000" in text
        assert "\n\n\n" not in text and text == text.strip()

    def test_plain_text_passthrough(self):
        assert sec_edgar.html_to_text("Plain   text\n\n\n\nfiling &amp; more") == "Plain text\n\nfiling & more"

    def test_uppercase_tags(self):
        assert sec_edgar.html_to_text("<HTML><SCRIPT>bad()</SCRIPT><P>Good</P></HTML>") == "Good"

    def test_parser_failure_falls_back_to_regex(self, monkeypatch):
        def boom(self, data):
            raise RuntimeError("bad markup")

        monkeypatch.setattr(sec_edgar._TextExtractor, "feed", boom)
        assert sec_edgar.html_to_text("<p>Hello</p><b>World</b>") == "Hello World"


class TestExtractSection:
    def test_10k_risk_factors_skips_table_of_contents(self):
        text = sec_edgar.html_to_text(ten_k_html())
        title, body, found = sec_edgar.extract_section(text, "10-K", "risk_factors")
        assert found is True and title == "Item 1A. Risk Factors"
        assert body.startswith("Item 1A. Risk Factors")
        assert "RISK BODY START" in body and body.rstrip().endswith("RISK BODY END.")
        assert "Unresolved Staff Comments" not in body

    def test_10k_mdna_with_curly_apostrophe_in_toc(self):
        text = sec_edgar.html_to_text(ten_k_html())
        title, body, found = sec_edgar.extract_section(text, "10-K", "mdna")
        assert found is True and title.startswith("Item 7.")
        assert "Financial Statements" not in body

    def test_10q_mdna(self):
        title, body, found = sec_edgar.extract_section(ten_q_text(), "10-Q", "mdna")
        assert found is True and title == "Part I, Item 2. Management's Discussion and Analysis"
        assert "MDNA START" in body and body.endswith("MDNA END.")
        assert "Quantitative and Qualitative" not in body

    def test_10q_amendment_uses_10q_family(self):
        assert sec_edgar.extract_section(ten_q_text(), "10-Q/A", "mdna")[2] is True

    def test_section_not_found_returns_document(self):
        text = "Item 1A. Risk Factors\nShort.\n" + "Nothing else here. " * 5
        title, body, found = sec_edgar.extract_section(text, "10-K", "risk_factors")
        assert (title, body, found) == ("Item 1A. Risk Factors", text, False)

    def test_heading_absent(self):
        text = "No items at all. " * 100
        assert sec_edgar.extract_section(text, "10-K", "legal_proceedings") == (
            "Item 3. Legal Proceedings",
            text,
            False,
        )

    def test_unknown_section_key(self):
        assert sec_edgar.extract_section("abc", "10-K", "nonsense") == ("nonsense", "abc", False)


@pytest.fixture
def filing_docs(sec):
    sec.get(archive("nvda-10k.htm")).mock(return_value=httpx.Response(200, text=ten_k_html()))
    sec.get(archive("nvda-10q.htm", "000104581026000015")).mock(return_value=httpx.Response(200, text=ten_q_text()))
    eight_k = (
        "<html><body><p>Item 2.02 Results of Operations and Financial Condition</p>"
        "<p>On August 28, 2026 NVIDIA reported revenue of $46.7 billion.</p>"
        "<p>Item 9.01 Financial Statements and Exhibits</p><p>ITEM 2.02 again</p></body></html>"
    )
    sec.get(archive("nvda-8k.htm", "000104581026000020")).mock(return_value=httpx.Response(200, text=eight_k))
    sec.get(archive("nvda-10q-old.htm", "000104581025000090")).mock(
        return_value=httpx.Response(200, text="Short old filing without items.")
    )
    return sec


class TestGetSection:
    def test_10k_risk_factors(self, filing_docs):
        s = sec_edgar.get_section("NVDA", "10-k", "risk_factors", None, 100_000)
        assert s.form == "10-K" and s.accession_number == "0001045810-26-000012"
        assert s.section_found is True and s.truncated is False
        assert s.total_characters == len(s.text)
        assert s.url == archive("nvda-10k.htm") and s.items_detected == []

    def test_truncation(self, filing_docs):
        s = sec_edgar.get_section("NVDA", "10-K", "risk_factors", None, 1000)
        assert s.truncated is True and len(s.text) == 1000 and s.total_characters > 1000

    def test_specific_accession(self, filing_docs):
        s = sec_edgar.get_section("NVDA", "10-Q", "mdna", "0001045810-25-000090", 5000)
        assert s.accession_number == "0001045810-25-000090"
        assert s.section_found is False and s.text == "Short old filing without items."

    def test_unknown_accession_falls_back_to_latest(self, filing_docs):
        s = sec_edgar.get_section("NVDA", "10-Q", "mdna", "nope", 5000)
        assert s.accession_number == "0001045810-26-000015" and s.section_found is True

    def test_8k_items_detected(self, filing_docs):
        s = sec_edgar.get_section("NVDA", "8-K", "risk_factors", None, 5000)
        assert s.section_title == "Current Report (8-K)" and s.section_found is True
        assert s.items_detected == ["2.02", "9.01"]
        assert "$46.7 billion" in s.text

    def test_no_filings_of_form(self, filing_docs):
        with pytest.raises(LookupError, match="No DEF 14A filings"):
            sec_edgar.get_section("NVDA", "DEF 14A", "business", None, 5000)

    def test_document_cached(self, filing_docs):
        sec_edgar.get_section("NVDA", "10-K", "risk_factors", None, 5000)
        sec_edgar.get_section("NVDA", "10-K", "mdna", None, 5000)
        route = filing_docs.routes[2]
        assert route.call_count == 1


# --------------------------------------------------------------------------- XBRL


def fact(val, end, start=None, form="10-K", fy=2026, fp="FY", filed="2026-02-21", accn="acc"):
    out = {"val": val, "end": end, "form": form, "fy": fy, "fp": fp, "filed": filed, "accn": accn}
    if start:
        out["start"] = start
    return out


FACTS = {
    "entityName": "NVIDIA Corporation",
    "facts": {
        "us-gaap": {
            "Revenues": {"units": {"USD": [fact(10e9, "2020-01-26", "2019-01-28")]}},  # stale concept
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        fact(130.5e9, "2026-01-25", "2025-01-27"),  # annual (363 days)
                        fact(60.9e9, "2025-01-26", "2024-01-29"),
                        fact(
                            39.3e9, "2026-01-25", "2025-10-27", form="10-K", fp="Q4"
                        ),  # 90d inside 10-K: not quarterly
                        fact(46.7e9, "2026-07-27", "2026-04-28", form="10-Q", fp="Q2", filed="2026-08-27"),  # quarterly
                        fact(90.8e9, "2026-07-27", "2026-01-26", form="10-Q", fp="Q2"),  # 6-month YTD: excluded
                        fact(1.0, "bad-date", "2026-01-01", form="10-Q"),  # unparseable: skipped
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {"USD": [fact(72.9e9, "2026-01-25", "2025-01-27"), fact(5.0, "2026-01-25", form="10-K")]}
            },
            "EarningsPerShareDiluted": {"units": {"USD/shares": [fact(2.94, "2026-01-25", "2025-01-27")]}},
            "Assets": {
                "units": {
                    "USD": [
                        fact(111.6e9, "2026-01-25"),
                        fact(125.0e9, "2026-07-27", form="10-Q", fp="Q2"),
                        fact(1.0, "2026-07-27", form="8-K"),  # wrong form
                    ]
                }
            },
        }
    },
}


@pytest.fixture
def xbrl(sec):
    sec.get(sec_edgar.COMPANY_FACTS_URL.format(cik=CIK)).mock(return_value=httpx.Response(200, json=FACTS))
    return sec


class TestXbrl:
    def test_annual_vs_quarterly_and_concept_fallback(self, xbrl):
        x = sec_edgar.get_xbrl_financials("nvda")
        assert x.ticker == "NVDA" and x.cik == CIK and x.company_name == "NVIDIA Corporation"
        rev = x.annual["revenue"]
        assert rev.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
        assert rev.value == 130.5e9 and rev.period_start == "2025-01-27" and rev.period_end == "2026-01-25"
        assert rev.form == "10-K" and rev.fiscal_year == 2026 and rev.fiscal_period == "FY" and rev.unit == "USD"
        q = x.quarterly["revenue"]
        assert q.value == 46.7e9 and q.form == "10-Q" and q.fiscal_period == "Q2" and q.filed == "2026-08-27"

    def test_duration_concept_requires_start_date(self, xbrl):
        x = sec_edgar.get_xbrl_financials("NVDA")
        assert x.annual["net_income"].value == 72.9e9
        assert "net_income" not in x.quarterly

    def test_instant_concepts(self, xbrl):
        x = sec_edgar.get_xbrl_financials("NVDA")
        assert x.annual["total_assets"].value == 111.6e9 and x.annual["total_assets"].period_start is None
        assert x.quarterly["total_assets"].value == 125.0e9
        assert x.annual["eps_diluted"].unit == "USD/shares"
        assert "gross_profit" not in x.annual

    def test_no_facts_raises(self, sec):
        sec.get(sec_edgar.COMPANY_FACTS_URL.format(cik=CIK)).mock(return_value=httpx.Response(200, json={"facts": {}}))
        with pytest.raises(LookupError, match="No standard us-gaap XBRL facts"):
            sec_edgar.get_xbrl_financials("NVDA")

    def test_pick_latest_prefers_later_filing_for_same_period(self):
        facts = [fact(1, "2026-01-25", filed="2026-02-21"), fact(2, "2026-01-25", form="10-K/A", filed="2026-04-01")]
        assert sec_edgar._pick_latest(facts, annual=True, is_duration=False)["val"] == 2

    def test_duration_days(self):
        assert sec_edgar._duration_days({"start": "2026-01-01", "end": "2026-04-01"}) == 90
        assert sec_edgar._duration_days({"end": "2026-04-01"}) is None
        assert sec_edgar._duration_days({"start": "x", "end": "2026-04-01"}) is None


class TestRateLimiting:
    def test_min_interval_limiter_sleeps(self, monkeypatch):
        from analyst.data import http

        clock = {"t": 100.0}
        sleeps = []
        monkeypatch.setattr(http.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(http.time, "sleep", lambda s: sleeps.append(s))
        limiter = MinIntervalLimiter(0.11)
        limiter.wait()
        clock["t"] += 0.05
        limiter.wait()
        assert sleeps == [pytest.approx(0.06)]

    def test_sec_retries_on_429(self, mock_http):
        route = mock_http.get(sec_edgar.TICKER_MAP_URL).mock(
            side_effect=[httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json=TICKERS)]
        )
        assert sec_edgar.resolve_cik("NVDA")[0] == CIK
        assert route.call_count == 2

    def test_sec_404_not_retried(self, mock_http):
        route = mock_http.get(sec_edgar.TICKER_MAP_URL).mock(return_value=httpx.Response(404))
        with pytest.raises(httpx.HTTPStatusError):
            sec_edgar.resolve_cik("NVDA")
        assert route.call_count == 1
