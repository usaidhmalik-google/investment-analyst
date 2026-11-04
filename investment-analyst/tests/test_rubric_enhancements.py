"""Comprehensive test suite for FDE Capstone Rubric enhancements.

Covers:
1. DLP & Data Classification (`analyst/guardrails/dlp.py`)
2. Hybrid RAG & Complex HTML Table Parsing (`analyst/data/rag.py`, `search_sec_filing`)
3. Circuit Breaker & Cache Telemetry (`analyst/tools/resilience.py`)
4. Strategy Plugin Registry (`analyst/strategies/engine.py`, `strategy_tools.py`)
5. Event-Driven Webhook Dispatcher & HMAC Signing (`analyst/services/webhooks.py`)
6. DR Snapshot Export/Restore (`analyst/services/report_store.py`)
7. Feature Flags, Token Cost Estimation, Versioned API (`/api/v1/*`), and `/api/metrics`
8. LLM Ops Metrics (ROUGE/BLEU, Precision/Recall/F1, Baseline Regression Detection)
9. Concurrent Load / SLA Verification & Failure-Injection Red-Teaming
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from analyst.api.app import create_app
from analyst.config import Settings, estimate_turn_cost_usd
from analyst.data.rag import (
    DeterministicEmbedder,
    FilingChunk,
    HybridFilingRetriever,
    VertexAIEmbedder,
    chunk_filing_section,
    evaluate_retrieval_quality,
    extract_html_tables,
    html_to_markdown_preserving_tables,
)
from analyst.guardrails.dlp import (
    DataClassification,
    classify_payload,
    redact_pii,
    redact_structured,
)
from analyst.services.analyst_service import AnalystService, StubRunner
from analyst.services.report_store import FirestoreReportStore, InMemoryReportStore
from analyst.services.telemetry import TelemetrySink
from analyst.services.webhooks import (
    WebhookDispatcher,
    WebhookEvent,
    sign_webhook_payload,
    verify_webhook_signature,
)
from analyst.strategies.engine import (
    StrategyPlugin,
    is_registered_strategy,
    list_registered_strategies,
    register_strategy,
    run_registered_strategy,
    unregister_strategy,
)
from analyst.tools.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    DataProviderError,
    TTLCache,
    cache_stats,
    circuit_breaker_snapshots,
    clear_all_caches,
    get_circuit_breaker,
    reset_all_circuit_breakers,
)
from analyst.tools.sec_tools import search_sec_filing
from analyst.tools.strategy_tools import run_strategy_backtest


# ---------------------------------------------------------------------------
# 1. DLP & Data Classification
# ---------------------------------------------------------------------------


class TestDlpAndClassification:
    def test_clean_financial_prompt_untouched(self) -> None:
        text = "Analyze AAPL FY24 10-K revenue of $391,035,000,000 and filing 0000320193-24-000123."
        res = redact_pii(text)
        assert not res.redacted
        assert res.redacted_text == text
        assert res.classification == DataClassification.INTERNAL_ANALYST_WORK_PRODUCT
        assert res.findings == ()

    def test_redacts_ssn_email_phone_acct_and_secret(self) -> None:
        text = (
            "Client SSN 123-45-6789, email jane.doe@example.com, "
            "phone (415) 555-0199, acct #1234567890, api_key: sk-secret9876543210"
        )
        res = redact_pii(text)
        assert res.redacted
        assert res.classification == DataClassification.RESTRICTED_PII_OR_CREDENTIAL
        assert "[REDACTED:US_SSN]" in res.redacted_text
        assert "[REDACTED:EMAIL_ADDRESS]" in res.redacted_text
        assert "[REDACTED:PHONE_NUMBER]" in res.redacted_text
        assert "[REDACTED:ACCOUNT_NUMBER]" in res.redacted_text
        assert "[REDACTED:CREDENTIAL_SECRET]" in res.redacted_text
        assert "123-45-6789" not in res.redacted_text
        assert "jane.doe@example.com" not in res.redacted_text
        types = {f.info_type for f in res.findings}
        assert {
            "US_SSN",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "ACCOUNT_NUMBER",
            "CREDENTIAL_SECRET",
        }.issubset(types)

    def test_redacts_valid_luhn_credit_card_and_ignores_invalid(self) -> None:
        # 4532015112830366 is a valid Luhn Visa test number
        valid_cc = "Card 4532-0151-1283-0366"
        res_valid = redact_pii(valid_cc)
        assert res_valid.redacted
        assert "[REDACTED:CREDIT_CARD]" in res_valid.redacted_text

        # Invalid Luhn number should not trigger credit card redaction
        invalid_cc = "Ref 4532-0151-1283-0367"
        res_invalid = redact_pii(invalid_cc)
        assert "CREDIT_CARD" not in {f.info_type for f in res_invalid.findings}

    def test_redact_pii_empty_string(self) -> None:
        res = redact_pii("")
        assert res.redacted_text == ""
        assert not res.redacted

    def test_redact_structured_nested_payload(self) -> None:
        payload = {
            "user": "john@acme.org",
            "notes": ["Call 123-45-6789", ("nested", "api_key=my_super_secret_token_123")],
            "count": 42,
        }
        cleaned = redact_structured(payload)
        assert cleaned["user"] == "[REDACTED:EMAIL_ADDRESS]"
        assert "[REDACTED:US_SSN]" in cleaned["notes"][0]
        assert "[REDACTED:CREDENTIAL_SECRET]" in cleaned["notes"][1][1]
        assert cleaned["count"] == 42

    def test_classify_payload_tiers(self) -> None:
        assert (
            classify_payload("AAPL", source="market_quote")
            == DataClassification.PUBLIC_MARKET_DATA
        )
        assert (
            classify_payload("Portfolio allocation", has_client_context=True)
            == DataClassification.CONFIDENTIAL_CLIENT_CONTEXT
        )
        assert (
            classify_payload("SSN 123-45-6789")
            == DataClassification.RESTRICTED_PII_OR_CREDENTIAL
        )


# ---------------------------------------------------------------------------
# 2. Hybrid RAG & Complex HTML Table Parsing
# ---------------------------------------------------------------------------


SAMPLE_SEC_HTML = """
<html>
<head><style>.hidden { display: none; }</style></head>
<body>
<h2>Item 7. Management's Discussion and Analysis</h2>
<p>Total net sales increased 2% driven by Services growth across all geographic segments.</p>
<table>
  <tr><th>Segment</th><th>FY24 ($M)</th><th>FY23 ($M)</th></tr>
  <tr><td>iPhone</td><td>201,183</td><td>200,583</td></tr>
  <tr><td>Services</td><td>96,169</td><td>85,200</td></tr>
  <tr><td>Wearables</td><td>37,005</td><td>39,845</td></tr>
</table>
<p>Supply chain concentration in East Asia remains a key operational risk factor under Item 1A.</p>
</body>
</html>
"""


class TestHybridRagAndHtmlTables:
    def test_extract_html_tables_to_gfm(self) -> None:
        tables = extract_html_tables(SAMPLE_SEC_HTML)
        assert len(tables) == 1
        assert "| Segment | FY24 ($M) | FY23 ($M) |" in tables[0]
        assert "| Services | 96,169 | 85,200 |" in tables[0]

    def test_html_to_markdown_preserving_tables(self) -> None:
        md = html_to_markdown_preserving_tables(SAMPLE_SEC_HTML)
        assert "Management's Discussion and Analysis" in md
        assert "| iPhone | 201,183 | 200,583 |" in md
        assert "display: none" not in md

    def test_chunk_filing_section_preserves_tables_and_handles_overlap(self) -> None:
        md = html_to_markdown_preserving_tables(SAMPLE_SEC_HTML)
        chunks = chunk_filing_section(
            md,
            ticker="AAPL",
            form="10-K",
            filing_date="2024-11-01",
            accession_number="0000320193-24-000123",
            item="7",
            max_chars=180,
            overlap_chars=30,
        )
        assert len(chunks) >= 2
        assert any(c.contains_table for c in chunks)
        assert all(c.ticker == "AAPL" and c.item == "7" for c in chunks)

        # Also test splitting an oversized single paragraph
        long_para = "Revenue grew steadily across enterprise cloud subscriptions. " * 40
        long_chunks = chunk_filing_section(
            long_para,
            ticker="MSFT",
            form="10-K",
            filing_date="2024-07-30",
            accession_number="0000950170-24-087843",
            item="7",
            max_chars=300,
            overlap_chars=50,
        )
        assert len(long_chunks) >= 4
        assert chunk_filing_section(
            "   ",
            ticker="MSFT",
            form="10-K",
            filing_date="2024-07-30",
            accession_number="0000950170-24-087843",
            item="7",
        ) == []

    def test_hybrid_retriever_bm25_dense_rrf_and_eval_metrics(self) -> None:
        chunks = [
            FilingChunk(
                chunk_id="c1",
                ticker="AAPL",
                form="10-K",
                filing_date="2024-11-01",
                accession_number="acc-1",
                item="7",
                chunk_index=0,
                text="| Segment | FY24 ($M) |\n| --- | --- |\n| Services | 96,169 |",
                contains_table=True,
                char_count=60,
            ),
            FilingChunk(
                chunk_id="c2",
                ticker="AAPL",
                form="10-K",
                filing_date="2024-11-01",
                accession_number="acc-1",
                item="1A",
                chunk_index=1,
                text="Semiconductor supply chain concentration in Taiwan and China poses tariff risks.",
                contains_table=False,
                char_count=80,
            ),
            FilingChunk(
                chunk_id="c3",
                ticker="AAPL",
                form="10-K",
                filing_date="2024-11-01",
                accession_number="acc-1",
                item="8",
                chunk_index=2,
                text="Share repurchases totaled $95 billion during fiscal year 2024.",
                contains_table=False,
                char_count=62,
            ),
        ]
        retriever = HybridFilingRetriever(chunks)
        hits = retriever.search("Services segment revenue table FY24", top_k=2)
        assert len(hits) == 2
        assert hits[0].chunk.chunk_id == "c1"
        assert hits[0].rrf_score > 0
        assert "citation" in hits[0].to_dict()

        # Verify retrieval quality evaluation metrics
        metrics = evaluate_retrieval_quality(
            retrieved_chunk_ids=[h.chunk.chunk_id for h in hits],
            relevant_chunk_ids={"c1"},
            k=2,
        )
        assert metrics["precision_at_k"] == 0.5
        assert metrics["recall_at_k"] == 1.0
        assert metrics["mrr"] == 1.0
        assert metrics["ndcg_at_k"] == 1.0

        # Empty retriever edge case
        empty_retriever = HybridFilingRetriever([])
        assert empty_retriever.search("anything") == []

    def test_vertex_ai_embedder_fallback(self) -> None:
        embedder = VertexAIEmbedder(project="")
        vecs = embedder.embed(["Revenue increased 10%", ""])
        assert len(vecs) == 2
        assert len(vecs[0]) == 256
        assert all(v == 0.0 for v in vecs[1])

    def test_search_sec_filing_tool_end_to_end(self) -> None:
        fake_section = {
            "ticker": "AAPL",
            "form": "10-K",
            "filing_date": "2024-11-01",
            "accession_number": "0000320193-24-000123",
            "item": "7",
            "item_title": "MD&A",
            "text": SAMPLE_SEC_HTML,
            "source": "sec_edgar",
            "source_url": "https://www.sec.gov/Archives/edgar/data/320193/10k.htm",
        }
        with patch("analyst.tools.sec_tools.sec_edgar.fetch_filing_section", return_value=fake_section):
            res = search_sec_filing("AAPL", query="Services FY24 revenue", form="10-K", item="7", top_k=3)
        assert res["status"] == "ok"
        assert res["ticker"] == "AAPL"
        assert res["tables_extracted"] >= 1
        assert len(res["retrieved_passages"]) >= 1
        assert res["retrieved_passages"][0]["contains_table"] is True


# ---------------------------------------------------------------------------
# 3. Circuit Breaker & Cache Telemetry
# ---------------------------------------------------------------------------


class TestCircuitBreakerAndCacheTelemetry:
    def setup_method(self) -> None:
        reset_all_circuit_breakers()
        clear_all_caches()

    def test_circuit_breaker_transitions_closed_open_half_open_closed(self) -> None:
        now = [100.0]
        cb = CircuitBreaker(
            "test_provider",
            failure_threshold=2,
            recovery_timeout_seconds=10.0,
            clock=lambda: now[0],
        )
        assert cb.state == "CLOSED"

        def fail() -> None:
            raise DataProviderError("upstream 503", status_code=503)

        with pytest.raises(DataProviderError):
            cb.call(fail)
        assert cb.state == "CLOSED"

        with pytest.raises(DataProviderError):
            cb.call(fail)
        assert cb.state == "OPEN"

        # While OPEN, subsequent calls fast-fail with CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(lambda: "should not execute")
        assert cb.snapshot().rejected_calls == 1

        # Advance clock past recovery timeout -> HALF_OPEN -> success -> CLOSED
        now[0] += 15.0
        assert cb.state == "HALF_OPEN"
        assert cb.call(lambda: "recovered") == "recovered"
        assert cb.state == "CLOSED"

    def test_global_circuit_breaker_registry_and_cache_stats(self) -> None:
        cb = get_circuit_breaker("yahoo_test", failure_threshold=3)
        cb.record_success()
        snaps = circuit_breaker_snapshots()
        assert "yahoo_test" in snaps
        assert snaps["yahoo_test"]["state"] == "CLOSED"

        cache: TTLCache[str] = TTLCache(ttl_seconds=60.0, name="unit_test_cache")
        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"
        assert cache.get("missing") is None
        stats = cache_stats()
        assert "unit_test_cache" in stats
        assert stats["unit_test_cache"]["hits"] == 1
        assert stats["unit_test_cache"]["misses"] == 1
        assert stats["unit_test_cache"]["hit_rate"] == 0.5


# ---------------------------------------------------------------------------
# 4. Strategy Plugin Registry
# ---------------------------------------------------------------------------


class TestStrategyPluginRegistry:
    def teardown_method(self) -> None:
        unregister_strategy("mean_reversion_zscore")

    def test_register_list_and_execute_custom_strategy_plugin(self) -> None:
        def _mean_rev_runner(bars: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
            return {
                "strategy": "mean_reversion_zscore",
                "parameters": params or {"lookback": 10},
                "bar_count": len(bars),
                "start_date": bars[0]["date"],
                "end_date": bars[-1]["date"],
                "trades": 3,
                "exposure_ratio": 0.4,
                "strategy_metrics": {
                    "cumulative_return": 0.12,
                    "cagr": 0.11,
                    "annualized_volatility": 0.14,
                    "sharpe_ratio": 0.78,
                    "max_drawdown": -0.05,
                },
                "benchmark_metrics": {
                    "cumulative_return": 0.08,
                    "cagr": 0.07,
                    "annualized_volatility": 0.16,
                    "sharpe_ratio": 0.45,
                    "max_drawdown": -0.09,
                },
                "excess_return": 0.04,
            }

        register_strategy(
            StrategyPlugin(
                name="mean_reversion_zscore",
                description="Bollinger Z-Score mean reversion plugin",
                runner=_mean_rev_runner,
                default_params={"lookback": 10},
            )
        )
        assert is_registered_strategy("mean_reversion_zscore")
        names = [p["name"] for p in list_registered_strategies()]
        assert "mean_reversion_zscore" in names

        fake_bars = {
            "bars": [
                {"date": f"2024-01-{i:02d}", "close": 100.0 + i}
                for i in range(1, 40)
            ],
            "source": "stub",
        }
        with patch("analyst.tools.strategy_tools.market.fetch_price_history", return_value=fake_bars):
            res = run_strategy_backtest("AAPL", strategy="mean_reversion_zscore")
        assert res["status"] == "ok"
        assert res["strategy"] == "mean_reversion_zscore"
        assert res["excess_return"] == 0.04


# ---------------------------------------------------------------------------
# 5. Event-Driven Webhooks & HMAC Signing
# ---------------------------------------------------------------------------


class TestWebhookDispatcher:
    def test_hmac_sign_and_verify(self) -> None:
        payload = '{"event_type":"analysis.completed","ticker":"AAPL"}'
        sig = sign_webhook_payload(payload, "top-secret")
        assert sig.startswith("sha256=")
        assert verify_webhook_signature(payload, sig, "top-secret")
        assert not verify_webhook_signature(payload, "sha256=deadbeef", "top-secret")
        assert not verify_webhook_signature(payload, sig, "")

    def test_dispatcher_in_process_and_http_delivery(self) -> None:
        received: list[WebhookEvent] = []
        dispatcher = WebhookDispatcher(target_url="https://hooks.example.com/events", secret="sec123")
        dispatcher.subscribe(received.append)

        mock_resp = MagicMock()
        mock_resp.status_code = 202
        with patch("analyst.services.webhooks.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
            evt = dispatcher.emit(
                "analysis.completed",
                {"report_id": "r1", "ticker": "NVDA", "recommendation": "BUY"},
            )
        assert len(received) == 1
        assert received[0].event_id == evt.event_id
        assert len(dispatcher.recent_deliveries()) == 1
        assert dispatcher.recent_deliveries()[0]["status"] == "delivered"


# ---------------------------------------------------------------------------
# 6. DR Snapshot Export / Restore
# ---------------------------------------------------------------------------


class TestDisasterRecoverySnapshots:
    def test_in_memory_snapshot_roundtrip(self) -> None:
        store = InMemoryReportStore()
        store.save({"report_id": "rep-1", "ticker": "AAPL", "created_at": "2025-01-01T00:00:00Z"})
        store.save({"report_id": "rep-2", "ticker": "MSFT", "created_at": "2025-01-02T00:00:00Z"})

        snap = store.export_snapshot()
        assert snap["report_count"] == 2

        new_store = InMemoryReportStore()
        restored = new_store.restore_snapshot(snap)
        assert restored == 2
        assert new_store.get("rep-1")["ticker"] == "AAPL"
        assert new_store.get("rep-2")["ticker"] == "MSFT"

    def test_firestore_snapshot_roundtrip_with_fake_client(self) -> None:
        docs: dict[str, dict[str, Any]] = {}

        class FakeDocRef:
            def __init__(self, doc_id: str) -> None:
                self.id = doc_id

            def set(self, payload: dict[str, Any]) -> None:
                docs[self.id] = dict(payload)

        class FakeSnap:
            def __init__(self, data: dict[str, Any]) -> None:
                self._data = data
                self.exists = True

            def to_dict(self) -> dict[str, Any]:
                return dict(self._data)

        class FakeCollection:
            def document(self, doc_id: str) -> FakeDocRef:
                return FakeDocRef(doc_id)

            def stream(self) -> list[FakeSnap]:
                return [FakeSnap(v) for v in docs.values()]

        class FakeClient:
            def collection(self, name: str) -> FakeCollection:
                return FakeCollection()

        fs_store = FirestoreReportStore(project="test-proj", collection="reports", client=FakeClient())
        restored = fs_store.restore_snapshot(
            {"reports": [{"report_id": "r-100", "ticker": "GOOGL"}]}
        )
        assert restored == 1
        exported = fs_store.export_snapshot()
        assert exported["report_count"] == 1
        assert exported["reports"][0]["ticker"] == "GOOGL"


# ---------------------------------------------------------------------------
# 7. Cost Estimation, Versioned API (/api/v1/*), and /api/metrics
# ---------------------------------------------------------------------------


class TestApiV1AndMetrics:
    def test_cost_estimation_flash_and_pro(self) -> None:
        flash_cost = estimate_turn_cost_usd(
            model="gemini-3-flash-preview", prompt_tokens=10_000, output_tokens=2_000
        )
        pro_cost = estimate_turn_cost_usd(
            model="gemini-2.5-pro", prompt_tokens=10_000, output_tokens=2_000
        )
        assert flash_cost > 0
        assert pro_cost > flash_cost

    def test_api_v1_routes_and_metrics_endpoint(self) -> None:
        settings = Settings(
            use_live_agent=False,
            enable_dlp_redaction=True,
            experiment_id="exp-tiering-01",
            experiment_variant="flash-specialist",
        )
        service = AnalystService(
            settings=settings,
            runner=StubRunner(),
            report_store=InMemoryReportStore(),
            telemetry=TelemetrySink(enabled=False),
        )
        app = create_app(service=service, settings=settings)
        client = TestClient(app)

        # Call /api/v1/chat with PII in prompt to verify DLP + v1 routing + metrics
        resp = client.post(
            "/api/v1/chat",
            json={
                "message": "Analyze AAPL for client john.smith@example.com",
                "ticker": "AAPL",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ticker"] == "AAPL"

        # Check persisted report has DLP metadata and cost estimation
        rep = client.get(f"/api/v1/reports/{body['report_id']}")
        assert rep.status_code == 200
        rep_json = rep.json()
        assert rep_json["dlp_redacted"] is True
        assert rep_json["estimated_cost_usd"] >= 0.0
        assert rep_json["experiment_id"] == "exp-tiering-01"

        # Check /api/v1/metrics and /api/metrics
        m_resp = client.get("/api/v1/metrics")
        assert m_resp.status_code == 200
        m_data = m_resp.json()
        assert m_data["turns_processed"] == 1
        assert m_data["dlp_redactions_triggered"] == 1
        assert m_data["feature_flags"]["enable_dlp_redaction"] is True
        assert "caches" in m_data
        assert "circuit_breakers" in m_data


# ---------------------------------------------------------------------------
# 8. LLM Ops Metrics (ROUGE/BLEU & Baseline Regression Detection)
# ---------------------------------------------------------------------------


class TestLlmOpsEvaluationEnhancements:
    def test_rouge_bleu_and_regression_detection(self) -> None:
        from evals.run_evals import compare_with_baseline, compute_rouge_and_bleu, run_suite

        scores = compute_rouge_and_bleu(
            candidate_text="Apple FY24 revenue reached $391B with strong Services margin expansion.",
            reference_terms=["Apple", "FY24", "revenue", "$391B", "Services", "margin"],
        )
        assert scores["rouge_1_f1"] > 0.3
        assert scores["rouge_l_f1"] > 0.2
        assert scores["bleu_4"] > 0.0

        dataset = Path(__file__).resolve().parents[1] / "evals" / "golden_dataset.json"
        summary = run_suite(dataset)
        assert summary["case_count"] == 10
        assert summary["avg_tool_f1"] >= 0.9
        assert summary["avg_rouge_1_f1"] > 0.0

        # Baseline comparison: identical baseline -> no regressions
        comp_ok = compare_with_baseline(summary, summary)
        assert comp_ok["regression_detected"] is False

        # Degraded current summary -> regression detected
        degraded = dict(summary)
        degraded["pass_rate"] = 0.5
        comp_bad = compare_with_baseline(degraded, summary)
        assert comp_bad["regression_detected"] is True
        assert any(r["metric"] == "pass_rate" for r in comp_bad["regressions"])


# ---------------------------------------------------------------------------
# 9. Concurrent Load / SLA Verification
# ---------------------------------------------------------------------------


class TestConcurrentLoadAndSla:
    def test_concurrent_25_turns_within_latency_sla(self) -> None:
        settings = Settings(use_live_agent=False)
        service = AnalystService(
            settings=settings,
            runner=StubRunner(),
            report_store=InMemoryReportStore(),
            telemetry=TelemetrySink(enabled=False),
        )

        async def _run_batch() -> list[dict[str, Any]]:
            tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
            tasks = [
                service.run_turn(
                    message=f"Provide an institutional investment memo for {tickers[i % 5]}",
                    ticker=tickers[i % 5],
                )
                for i in range(25)
            ]
            return await asyncio.gather(*tasks)

        results = asyncio.run(_run_batch())
        assert len(results) == 25
        latencies = sorted(r["latency_ms"] for r in results)
        p95 = latencies[int(0.95 * (len(latencies) - 1))]
        # Stub orchestration SLA must be well below 500ms p95 in-process
        assert p95 < 500.0
        snap = service.metrics_snapshot()
        assert snap["turns_processed"] == 25
        assert snap["total_tokens"] > 0
