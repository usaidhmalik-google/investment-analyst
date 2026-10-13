"""Post-generation fact checker: number extraction, tolerance by displayed precision, citations."""

from __future__ import annotations

import pytest

from analyst.guardrails.fact_check import cited_ids, evidence_numbers, extract_numbers, fact_check


def values(text: str, **kw) -> list[float]:
    return [t.value for t in extract_numbers(text, **kw)]


def ev(data: dict, cid: str = "Q:TEST") -> dict:
    return {cid: {"citation": {"id": cid}, "data": data}}


class TestExtractNumbers:
    @pytest.mark.parametrize(
        ("text", "value", "decimals", "scale", "is_percent"),
        [
            ("$3.15T", 3.15e12, 2, 1e12, False),
            ("$1,234.56", 1234.56, 2, 1.0, False),
            ("1,234,567", 1234567.0, 0, 1.0, False),
            ("$60.92B", 60.92e9, 2, 1e9, False),
            ("45M", 45e6, 0, 1e6, False),
            ("12K", 12e3, 0, 1e3, False),
            ("3.2 billion", 3.2e9, 1, 1e9, False),
            ("3.5 trillion", 3.5e12, 1, 1e12, False),
            ("1.5 tn", 1.5e12, 1, 1e12, False),
            ("2bn", 2e9, 0, 1e9, False),
            ("9mm", 9e6, 0, 1e6, False),
            ("48 million", 48e6, 0, 1e6, False),
            ("7 thousand", 7e3, 0, 1e3, False),
            ("12.5%", 12.5, 1, 1.0, True),
            ("12.5 %", 12.5, 1, 1.0, True),
            ("12.5 percent", 12.5, 1, 1.0, True),
            ("3 pp", 3.0, 0, 1.0, True),
            ("48.2x", 48.2, 1, 1.0, False),
            ("-3.78%", -3.78, 2, 1.0, True),
            ("−2.5%", -2.5, 1, 1.0, True),  # unicode minus
            ("$5", 5.0, 0, 1.0, False),
            ("128.49", 128.49, 2, 1.0, False),
        ],
    )
    def test_parses_financial_figures(self, text, value, decimals, scale, is_percent):
        (token,) = extract_numbers(text)
        assert token.value == pytest.approx(value)
        assert (token.decimals, token.scale, token.is_percent) == (decimals, scale, is_percent)
        assert token.text == text

    def test_figures_inside_prose(self):
        text = "NVDA closed at $128.50, up 1.9%, with a market cap of $3.15T and a P/E of 48.2x."
        assert values(text) == pytest.approx([128.50, 1.9, 3.15e12, 48.2])

    def test_suffix_requires_word_boundary(self):
        # "Microsoft" must not turn "5 M" into a scale; "Mn" or "Mar" are not suffixes either.
        assert values("$5 Microsoft") == [5.0]
        assert values("$5 Mar") == [5.0]

    @pytest.mark.parametrize(
        "text",
        [
            "[Q:NVDA]",
            "[SEC:NVDA:10-K:0001045810-26-000012]",
            "see [link](https://example.com/report/2025/12345)",
            "https://finance.yahoo.com/quote/NVDA/history?p=123456",
            "on 2026-09-15",
            "as of 2026-09-15T20:00:00+00:00",
            "Sept 15, 2026",
            "on Sep 3rd",
            "in 2025",
            "the 10-K, 10-Q, 8-K, 10-K/A and 13F-HR filings",
            "DEF 14A proxy and Form 4",
            "Item 1A and Item 7 and Item 2.02",
            "the 50-day and 200-day moving averages over 52 weeks",
            "a 3-month and 6 month window",
            "5d, 1mo, 1y and 2w windows",
            "RSI(14), SMA(50), Bollinger Bands(20, 2) and MACD(12, 26, 9)",
            "RSI14, SMA-200, ATR_14",
            "Q2 FY2025, Q3 '24, H1 2026 and FY26",
            "the 1st and 22nd",
            "Gemini 2.5 Pro",
            "1. First point 2. Second point 3 items",
            "S:NVDA:momentum",
        ],
    )
    def test_ignores_non_financial_digits(self, text):
        assert extract_numbers(text) == []

    def test_small_bare_integers_and_years_skipped_only_when_trivial(self):
        assert values("3 risks in 2024") == []
        assert values("3 risks in 2024", skip_trivial=False) == [3.0, 2024.0]
        assert values("11 analysts") == [11.0]  # > 10 is checked
        assert values("2.0 points") == [2.0]  # decimals make it a figure
        assert values("$3") == [3.0]  # currency makes it a figure

    def test_year_range_bounds(self):
        assert values("1899 and 2101") == [1899.0, 2101.0]
        assert values("1900 and 2100") == []


class TestEvidenceNumbers:
    def test_walks_nested_data_and_strings(self):
        evidence = {
            "Q:A": {
                "citation": {"id": "Q:A"},
                "data": {"price": 10.5, "flag": True, "none": None, "nan": float("nan")},
            },
            "N:A:1": {"citation": {}, "data": {"title": "Revenue up 12.5% to $4.2B", "tags": ["7.5x", 3]}},
            "raw": {"inf": float("inf"), "n": 2},  # record without a data key
        }
        assert evidence_numbers(evidence) == pytest.approx(sorted([10.5, 12.5, 4.2e9, 7.5, 3.0, 2.0]))


class TestFactCheck:
    def test_empty_narrative_is_verified(self):
        result = fact_check("", {})
        assert result.verified is True and result.checked_numbers == 0 and result.accuracy == 1.0

    def test_narrative_without_numbers_is_verified(self):
        assert fact_check("Shares rallied on strong demand [Q:NVDA].", {}).verified is True

    @pytest.mark.parametrize(
        ("narrative", "evidence_value", "ok"),
        [
            ("market cap of $3.15T", 3_151_234_567_890, True),
            ("market cap of $3.2T", 3.15e12, True),  # 1dp: +/- 0.05T
            ("market cap of $3.3T", 3.15e12, False),
            ("market cap of $3T", 3.4e12, True),  # 0dp: +/- 0.5T
            ("price of $128.49", 128.50, False),
            ("price of $128.50", 128.50, True),
            ("price of $128.5", 128.54, True),
            ("price of $128.5", 128.56, False),
            ("revenue of $60.92B", 60_920_000_000, True),
            ("revenue of $61B", 60_920_000_000, True),
            ("revenue of 60,920,000,000", 60_920_000_000, True),
            ("volume of 48.5M shares", 48_500_000, True),
            ("growth of 122.4%", 122.4, True),
            ("growth of 122%", 122.4, True),
            ("growth of 123%", 122.4, False),
        ],
    )
    def test_tolerance_from_displayed_precision(self, narrative, evidence_value, ok):
        result = fact_check(narrative, ev({"x": evidence_value}))
        assert result.verified is ok
        assert result.checked_numbers == 1

    def test_signed_moves_match_absolute_values(self):
        evidence = ev({"change_pct": -3.78, "change": -4.85})
        assert fact_check("shares fell 3.78%, down $4.85", evidence).verified is True
        assert fact_check("a -3.78% move", evidence).verified is True

    def test_numbers_inside_evidence_strings_count(self):
        evidence = ev({"title": "Nvidia guides to $32.5B revenue, up 80%"}, cid="N:NVDA:1")
        result = fact_check("Management guided to $32.5B [N:NVDA:1], up 80% [N:NVDA:1].", evidence)
        assert result.verified is True and result.checked_numbers == 2

    def test_filing_text_numbers_count(self):
        evidence = ev({"text": "We had approximately 29,600 employees and $26.0 billion in cash."}, cid="SEC:X:10-K:1")
        assert fact_check("The company employs about 29,600 people.", evidence).verified is True

    def test_unverified_reported_deduped_in_order(self):
        evidence = ev({"price": 128.5})
        narrative = "Trades at $128.50 [Q:NVDA], target $999.99, again $999.99, and 42.1x."
        result = fact_check(narrative, evidence)
        assert result.verified is False
        assert result.checked_numbers == 4
        assert result.matched_numbers == 1
        assert result.unverified_numbers == ["$999.99", "42.1x"]
        assert result.accuracy == 0.25

    def test_citation_digits_do_not_count(self):
        evidence = ev({"price": 435.5})
        narrative = "MSFT is at $435.50 [Q:MSFT] per the 10-K filed 2026-02-21 [SEC:MSFT:10-K:0000789019-26-000001]."
        result = fact_check(narrative, evidence)
        assert result.verified is True and result.checked_numbers == 1

    def test_offline_fixture_brief_verifies(self):
        from analyst.data import fixtures
        from analyst.tools.evidence import dump

        evidence = {
            "Q:NVDA": {"citation": {}, "data": dump(fixtures.quote("NVDA"))},
            "M:NVDA": {"citation": {}, "data": dump(fixtures.metrics("NVDA"))},
        }
        narrative = (
            "NVDA trades at $128.50 [Q:NVDA], up 1.9% [Q:NVDA] (+$2.40), market cap $3.15T, 48.2x trailing "
            "earnings and 32.5x forward. Revenue of $60.92B grew 122.4% with a 75.1% gross margin [M:NVDA]; "
            "45 analysts rate it BUY with a $145 target."
        )
        result = fact_check(narrative, evidence)
        assert result.verified is True, result.unverified_numbers
        assert result.checked_numbers == 11


class TestCitedIds:
    def test_order_and_dedupe(self):
        text = (
            "A [Q:NVDA] B [M:NVDA] C [Q:NVDA] D [N:NVDA:2] E [SEC:NVDA:10-K:0001045810-26-000001] F [S:NVDA:momentum]"
        )
        assert cited_ids(text) == [
            "Q:NVDA",
            "M:NVDA",
            "N:NVDA:2",
            "SEC:NVDA:10-K:0001045810-26-000001",
            "S:NVDA:momentum",
        ]

    def test_all_prefixes(self):
        text = "[Q:A][H:A:5d][M:A][N:A:1][SEC:A:8-K:1][XBRL:A][S:A:value]"
        assert cited_ids(text) == ["Q:A", "H:A:5d", "M:A", "N:A:1", "SEC:A:8-K:1", "XBRL:A", "S:A:value"]

    def test_ignores_unknown_prefixes_and_markdown_links(self):
        assert cited_ids("[X:NVDA] [link](http://a) [Q NVDA] [note]") == []


def test_sma_window_with_space_is_not_a_figure_but_value_is():
    tokens = [t.text for t in extract_numbers("Price $88.38 sits above the SMA 50 at $87.99 and EMA 200.")]
    assert tokens == ["$88.38", "$87.99"]


def test_comma_formatted_count_in_year_range_is_checked():
    tokens = [t.value for t in extract_numbers("The company has 2,050 employees and was founded in 1993.")]
    assert tokens == [2050.0]
