"""ADK tool functions: evidence recording, citation ids, argument validation and error shaping."""

from __future__ import annotations

import pytest

from analyst.data import fixtures, market
from analyst.strategies import engine
from analyst.tools import evidence
from analyst.tools.evidence import EVIDENCE_KEY, get_evidence, record_evidence, safe_tool
from analyst.tools.market_tools import (
    DATA_GATHERER_TOOLS,
    MAX_BARS_TO_MODEL,
    get_company_news,
    get_financial_metrics,
    get_price_history,
    get_stock_quote,
)
from analyst.tools.sec_tools import (
    SEC_FILING_TOOLS,
    get_sec_filing_section,
    get_sec_reported_financials,
    list_sec_filings,
)
from analyst.tools.strategy_tools import STRATEGY_TOOLS, evaluate_strategy


def citation(ctx, cid):
    return ctx.state[EVIDENCE_KEY][cid]["citation"]


class TestEvidenceRegistry:
    def test_record_reassigns_state(self, tool_context):
        record_evidence(tool_context, citation_id="Q:A", type="quote", title="t", source="s", data={"price": 1})
        first = tool_context.state[EVIDENCE_KEY]
        record_evidence(tool_context, citation_id="Q:B", type="quote", title="t", source="s", data={"price": 2})
        second = tool_context.state[EVIDENCE_KEY]
        assert first is not second  # new dict so ADK records a state delta
        assert set(first) == {"Q:A"} and set(second) == {"Q:A", "Q:B"}

    def test_record_payload_and_citation(self, tool_context):
        out = record_evidence(
            tool_context, citation_id="N:A:1", type="news", title="T", source="S", url="u", as_of="d", data={"x": 1}
        )
        assert out == {"citation_id": "N:A:1", "x": 1}
        assert tool_context.state[EVIDENCE_KEY]["N:A:1"] == {
            "citation": {"id": "N:A:1", "type": "news", "title": "T", "source": "S", "url": "u", "as_of": "d"},
            "data": {"x": 1},
        }

    def test_record_without_context(self):
        assert record_evidence(None, citation_id="Q:A", type="quote", title="t", source="s", data={}) == {
            "citation_id": "Q:A"
        }

    def test_get_evidence(self):
        assert get_evidence(None) == {}
        assert get_evidence({}) == {}
        state = {EVIDENCE_KEY: {"Q:A": {}}}
        copy = get_evidence(state)
        assert copy == {"Q:A": {}} and copy is not state[EVIDENCE_KEY]

    def test_invalid_evidence_type_rejected(self, tool_context):
        with pytest.raises(ValueError):
            record_evidence(tool_context, citation_id="X", type="bogus", title="t", source="s", data={})


class TestSafeTool:
    def test_value_error_is_invalid_argument(self):
        @safe_tool
        def tool():
            raise ValueError("bad input")

        assert tool() == {"error": "bad input", "error_type": "invalid_argument"}

    def test_other_errors_are_data_unavailable(self):
        @safe_tool
        def tool():
            raise RuntimeError("provider down")

        result = tool()
        assert result["error_type"] == "data_unavailable"
        assert result["error"] == "Data unavailable from external providers: provider down"
        assert "Do not estimate" in result["instruction"]

    def test_preserves_metadata_and_passthrough(self):
        @safe_tool
        def my_tool(x: int) -> dict:
            """Doc."""
            return {"x": x}

        assert my_tool.__name__ == "my_tool" and my_tool.__doc__ == "Doc."
        assert my_tool(3) == {"x": 3}

    def test_dump_excludes_none(self):
        assert evidence.dump(fixtures.news("KO", 1).articles[0]) == {
            "title": "Coca-Cola raises full-year organic revenue outlook on pricing",
            "publisher": "Reuters",
            "published": "2026-09-12",
        }


class TestMarketTools:
    def test_registry(self):
        assert [get_stock_quote, get_price_history, get_financial_metrics, get_company_news] == DATA_GATHERER_TOOLS

    def test_quote(self, tool_context):
        out = get_stock_quote("nvda", tool_context=tool_context)
        assert out["citation_id"] == "Q:NVDA" and out["price"] == 128.5
        c = citation(tool_context, "Q:NVDA")
        assert c["type"] == "quote" and c["title"] == "NVIDIA Corporation real-time quote"
        assert c["source"] == "Offline Fixture" and c["url"] is None and c["as_of"] == fixtures.AS_OF

    def test_quote_yahoo_url(self, tool_context, monkeypatch):
        q = fixtures.quote("NVDA").model_copy(update={"source": "Yahoo Finance"})
        monkeypatch.setattr(market, "get_quote", lambda t: q)
        get_stock_quote("NVDA", tool_context=tool_context)
        assert citation(tool_context, "Q:NVDA")["url"] == "https://finance.yahoo.com/quote/NVDA"

    def test_history_truncates_bars(self, tool_context):
        out = get_price_history("NVDA", "1mo", tool_context=tool_context)
        assert out["citation_id"] == "H:NVDA:1mo"
        assert "bars" not in out
        assert len(out["recent_bars"]) == MAX_BARS_TO_MODEL == 10
        full = fixtures.history("NVDA", "1mo")
        assert out["recent_bars"][-1]["close"] == full.bars[-1].close
        assert out["recent_bars"][0]["date"] == full.bars[-10].date
        c = citation(tool_context, "H:NVDA:1mo")
        assert c["type"] == "history" and c["title"] == f"NVDA price history ({full.start_date} to {full.end_date})"
        assert tool_context.state[EVIDENCE_KEY]["H:NVDA:1mo"]["data"]["recent_bars"] == out["recent_bars"]

    def test_history_short_period_keeps_all(self, tool_context):
        assert len(get_price_history("NVDA", tool_context=tool_context)["recent_bars"]) == 5  # default 5d

    def test_history_yahoo_url(self, tool_context, monkeypatch):
        h = fixtures.history("NVDA", "5d").model_copy(update={"source": "Yahoo Finance"})
        monkeypatch.setattr(market, "get_history", lambda t, p: h)
        get_price_history("NVDA", "5d", tool_context=tool_context)
        assert citation(tool_context, "H:NVDA:5d")["url"] == "https://finance.yahoo.com/quote/NVDA/history"

    def test_history_invalid_period(self, tool_context):
        out = get_price_history("NVDA", "10y", tool_context=tool_context)
        assert out["error_type"] == "invalid_argument"
        assert EVIDENCE_KEY not in tool_context.state

    def test_metrics(self, tool_context, monkeypatch):
        out = get_financial_metrics("AAPL", tool_context=tool_context)
        assert out["citation_id"] == "M:AAPL" and out["trailing_eps"] == 6.57
        c = citation(tool_context, "M:AAPL")
        assert c["type"] == "metrics" and c["url"] is None
        m = fixtures.metrics("AAPL").model_copy(update={"source": "Yahoo Finance"})
        monkeypatch.setattr(market, "get_metrics", lambda t: m)
        get_financial_metrics("AAPL", tool_context=tool_context)
        assert citation(tool_context, "M:AAPL")["url"] == "https://finance.yahoo.com/quote/AAPL/key-statistics"

    def test_news(self, tool_context):
        out = get_company_news("NVDA", 2, tool_context=tool_context)
        assert out["ticker"] == "NVDA" and out["source"] == "Offline Fixture"
        assert [a["citation_id"] for a in out["articles"]] == ["N:NVDA:1", "N:NVDA:2"]
        c = citation(tool_context, "N:NVDA:1")
        assert c["type"] == "news" and c["source"] == "Reuters" and c["as_of"] == "2026-09-14"
        assert c["title"].startswith("Nvidia Blackwell Ultra")

    def test_news_falls_back_to_feed_source_and_as_of(self, tool_context, monkeypatch):
        from analyst.data.schemas import NewsArticle, NewsFeed

        feed = NewsFeed(ticker="X", articles=[NewsArticle(title="t")], source="Yahoo Finance", as_of="2026-01-01")
        monkeypatch.setattr(market, "get_news", lambda t, n: feed)
        get_company_news("X", tool_context=tool_context)
        c = citation(tool_context, "N:X:1")
        assert c["source"] == "Yahoo Finance" and c["as_of"] == "2026-01-01"

    def test_invalid_ticker(self, tool_context):
        assert get_stock_quote("NV DA", tool_context=tool_context)["error_type"] == "invalid_argument"

    def test_unknown_ticker_is_data_unavailable(self, tool_context):
        out = get_stock_quote("ZZZZ", tool_context=tool_context)
        assert out["error_type"] == "data_unavailable" and "No offline fixture" in out["error"]


class TestSecTools:
    def test_registry(self):
        assert [list_sec_filings, get_sec_filing_section, get_sec_reported_financials] == SEC_FILING_TOOLS

    def test_list_defaults(self, tool_context):
        out = list_sec_filings("nvda", tool_context=tool_context)
        assert out["ticker"] == "NVDA" and out["cik"] == "0001045810" and out["company_name"] == "NVIDIA Corporation"
        assert [f["form"] for f in out["filings"]] == ["10-K", "10-Q", "8-K"]
        first = out["filings"][0]
        assert first["citation_id"] == f"SEC:NVDA:10-K:{first['accession_number']}"
        c = citation(tool_context, first["citation_id"])
        assert c["type"] == "sec_filing" and c["title"] == "NVIDIA Corporation 10-K filed 2026-02-21"
        assert c["as_of"] == "2026-02-21"

    def test_list_forms_upper_cased_and_limit_clamped(self, tool_context, monkeypatch):
        seen = []
        real = market.list_filings
        monkeypatch.setattr(market, "list_filings", lambda t, f, n: seen.append((t, f, n)) or real(t, f, n))
        list_sec_filings("NVDA", ["10-k", "def 14a"], limit=99, tool_context=tool_context)
        list_sec_filings("NVDA", ["8-k"], limit=0, tool_context=tool_context)
        assert seen == [("NVDA", ("10-K", "DEF 14A"), 20), ("NVDA", ("8-K",), 1)]

    def test_list_rejects_unsupported_forms(self, tool_context):
        out = list_sec_filings("NVDA", ["10-K", "S-1"], tool_context=tool_context)
        assert out["error_type"] == "invalid_argument" and "S-1" in out["error"]

    def test_section(self, tool_context):
        out = get_sec_filing_section("NVDA", "10-k", "risk_factors", tool_context=tool_context)
        assert out["citation_id"].startswith("SEC:NVDA:10-K:")
        assert out["section_found"] is True
        c = citation(tool_context, out["citation_id"])
        assert c["title"] == "NVDA 10-K (2026-02-21) — Item 1A. Risk Factors"

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"form_type": "S-1"}, "form_type must be 10-K, 10-Q or 8-K"),
            ({"section": "poetry"}, "section must be one of"),
        ],
    )
    def test_section_argument_validation(self, tool_context, kwargs, message):
        out = get_sec_filing_section("NVDA", tool_context=tool_context, **kwargs)
        assert out["error_type"] == "invalid_argument" and message in out["error"]

    @pytest.mark.parametrize(("requested", "clamped"), [(10, 1000), (6000, 6000), (10**6, 15000)])
    def test_section_max_chars_clamped(self, tool_context, monkeypatch, requested, clamped):
        seen = []
        real = market.get_filing_section
        monkeypatch.setattr(market, "get_filing_section", lambda *a: seen.append(a) or real(*a))
        get_sec_filing_section("NVDA", "10-Q", "mdna", "acc-1", requested, tool_context=tool_context)
        assert seen == [("NVDA", "10-Q", "mdna", "acc-1", clamped)]

    def test_xbrl(self, tool_context):
        out = get_sec_reported_financials("MSFT", tool_context=tool_context)
        assert out["citation_id"] == "XBRL:MSFT"
        assert out["annual"]["revenue"]["value"] == 245.12e9
        c = citation(tool_context, "XBRL:MSFT")
        assert c["type"] == "sec_financials"
        assert c["url"] == "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000789019"


class TestStrategyTool:
    def test_registry(self):
        assert [evaluate_strategy] == STRATEGY_TOOLS

    @pytest.mark.parametrize("strategy", ["momentum", "value", "swing", "income"])
    def test_offline_matches_engine(self, tool_context, strategy):
        out = evaluate_strategy("nvda", strategy, tool_context=tool_context)
        cid = f"S:NVDA:{strategy}"
        assert out["citation_id"] == cid and out["strategy"] == strategy and out["ticker"] == "NVDA"
        if strategy == "momentum":
            expected = engine.evaluate_momentum("NVDA", fixtures.history("NVDA", "1y").bars, fixtures.AS_OF)
        elif strategy == "swing":
            expected = engine.evaluate_swing("NVDA", fixtures.history("NVDA", "1y").bars, fixtures.AS_OF)
        elif strategy == "value":
            expected = engine.evaluate_value("NVDA", fixtures.quote("NVDA"), fixtures.metrics("NVDA"), fixtures.AS_OF)
        else:
            expected = engine.evaluate_income(
                "NVDA", fixtures.quote("NVDA"), fixtures.metrics("NVDA"), fixtures.dividends("NVDA"), fixtures.AS_OF
            )
        assert out["signal"] == expected.signal and out["score"] == expected.score
        assert out["signal"] != engine.INSUFFICIENT
        c = citation(tool_context, cid)
        assert c["type"] == "strategy" and c["source"] == "Strategy Engine"
        assert c["title"] == f"NVDA {strategy} strategy evaluation: {expected.signal}"

    def test_strategy_name_normalised(self, tool_context):
        assert evaluate_strategy("KO", "  Income ", tool_context=tool_context)["citation_id"] == "S:KO:income"

    def test_unknown_strategy(self, tool_context):
        out = evaluate_strategy("NVDA", "yolo", tool_context=tool_context)
        assert out["error_type"] == "invalid_argument" and "strategy must be one of" in out["error"]

    def test_invalid_ticker(self, tool_context):
        assert evaluate_strategy("$$$", "value", tool_context=tool_context)["error_type"] == "invalid_argument"

    def test_offline_value_is_deterministic(self, tool_context):
        out = evaluate_strategy("NVDA", "value", tool_context=tool_context)
        assert (out["signal"], out["score"]) == ("OVERVALUED", 0)
