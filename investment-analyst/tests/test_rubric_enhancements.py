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
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.adk.events import Event
from google.genai import types

from analyst.agents import FINANCIAL_ANALYST, build_root_agent
from analyst.api.app import create_app
from analyst.api.schemas import ChatRequest
from analyst.config import Settings, estimate_turn_cost_usd
from analyst.data.rag import (
    HybridFilingRetriever,
    VertexAIEmbedder,
    chunk_filing_section,
    cosine_similarity,
    evaluate_retrieval_quality,
    extract_html_tables,
    html_to_markdown_preserving_tables,
)
from analyst.data.schemas import StrategySignal
from analyst.guardrails.dlp import (
    DataClassification,
    classify_payload,
    scan_and_redact,
)
from analyst.services.analyst_service import AnalystService, UserIdentity
from analyst.services.report_store import FirestoreReportStore, InMemoryReportStore
from analyst.services.telemetry_sink import TelemetrySink
from analyst.services.webhooks import (
    WebhookDispatcher,
    WebhookEvent,
    sign_webhook_payload,
    verify_webhook_signature,
)
from analyst.strategies.engine import (
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
from analyst.tools.strategy_tools import evaluate_strategy

# ---------------------------------------------------------------------------
# 1. DLP & Data Classification
# ---------------------------------------------------------------------------


class TestDlpAndClassification:
    def test_clean_financial_prompt_untouched(self) -> None:
        text = "Analyze NVDA FY26 10-K revenue of $130,497,000,000 and filing 0001045810-26-000021."
        res = scan_and_redact(text)
        assert not res.has_pii
        assert res.sanitized_text == text
        assert res.classification == DataClassification.INTERNAL_ANALYST_WORK_PRODUCT
        assert res.findings == []
        assert res.to_metadata()["redacted_count"] == 0

    def test_redacts_ssn_email_phone_acct_and_secret(self) -> None:
        text = (
            "Client SSN 123-45-6789, email jane.doe@example.com, "
            "phone (415) 555-0199, account #1234567890, Bearer abcdefghijklmnopqrstuvwxyz1234"
        )
        res = scan_and_redact(text)
        assert res.has_pii
        assert res.classification == DataClassification.RESTRICTED_PII_OR_CREDENTIAL
        assert "[REDACTED:SSN]" in res.sanitized_text
        assert "[REDACTED:EMAIL]" in res.sanitized_text
        assert "[REDACTED:PHONE]" in res.sanitized_text
        assert "[REDACTED:ACCOUNT_NUMBER]" in res.sanitized_text
        assert "[REDACTED:SECRET]" in res.sanitized_text
        assert "123-45-6789" not in res.sanitized_text
        assert "jane.doe@example.com" not in res.sanitized_text
        cats = set(res.categories)
        assert {
            "US_SSN",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "ACCOUNT_NUMBER",
            "CREDENTIAL_SECRET",
        }.issubset(cats)

    def test_redacts_valid_luhn_credit_card_and_ignores_invalid(self) -> None:
        # 4532015112830366 is a valid Luhn Visa test number
        valid_cc = "Card 4532-0151-1283-0366"
        res_valid = scan_and_redact(valid_cc)
        assert res_valid.has_pii
        assert "[REDACTED:CREDIT_CARD]" in res_valid.sanitized_text

        # Invalid Luhn number and all-identical digits should not trigger credit card redaction
        invalid_cc = "Ref 4532-0151-1283-0367 and 0000-0000-0000-0000"
        res_invalid = scan_and_redact(invalid_cc)
        assert "CREDIT_CARD" not in set(res_invalid.categories)

    def test_scan_and_redact_empty_string(self) -> None:
        res = scan_and_redact("")
        assert res.sanitized_text == ""
        assert not res.has_pii

    def test_classify_payload_tiers(self) -> None:
        assert classify_payload("sec_edgar") == DataClassification.PUBLIC_MARKET_DATA
        assert classify_payload("portfolio") == DataClassification.CONFIDENTIAL_CLIENT_CONTEXT
        assert classify_payload("memo") == DataClassification.INTERNAL_ANALYST_WORK_PRODUCT
        assert classify_payload("sec_edgar", has_pii=True) == DataClassification.RESTRICTED_PII_OR_CREDENTIAL


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
        assert "| Segment | FY24 ($M) | FY23 ($M) |" in tables[0]["markdown"]
        assert "| Services | 96,169 | 85,200 |" in tables[0]["markdown"]
        assert tables[0]["row_count"] == 4
        assert tables[0]["column_count"] == 3

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
            section="mdna",
            accession_number="0000320193-25-000079",
            chunk_size=220,
            chunk_overlap=40,
        )
        assert len(chunks) >= 2
        assert all(c.ticker == "AAPL" and c.section == "mdna" for c in chunks)

        # Also test splitting a long single sentence and empty text
        long_para = "Revenue grew steadily across enterprise cloud subscriptions. " * 30
        long_chunks = chunk_filing_section(
            long_para,
            ticker="MSFT",
            form="10-K",
            section="mdna",
            accession_number="acc-2",
            chunk_size=300,
            chunk_overlap=50,
        )
        assert len(long_chunks) >= 4
        assert chunk_filing_section("   ", ticker="MSFT") == []

    def test_hybrid_retriever_bm25_dense_rrf_and_eval_metrics(self) -> None:
        chunks = chunk_filing_section(
            (
                "Services segment revenue reached $96,169 million in FY24 with gross margin expansion.\n\n"
                + ("Semiconductor supply chain concentration in Taiwan and China poses tariff risks. " * 8)
                + "\n\n"
                + (
                    "Share repurchases totaled $95 billion during fiscal year 2024 under the capital return program. "
                    * 8
                )
            ),
            ticker="AAPL",
            form="10-K",
            section="mdna",
            accession_number="acc-1",
            chunk_size=250,
            chunk_overlap=30,
        )
        retriever = HybridFilingRetriever(chunks)
        hits = retriever.search("Taiwan semiconductor supply chain tariff risks", top_k=2)
        assert len(hits) == 2
        assert "Taiwan" in hits[0].chunk.text
        assert hits[0].rrf_score > 0

        # Verify retrieval quality evaluation metrics
        relevant = {c.chunk_id for c in chunks if "Taiwan" in c.text}
        metrics = evaluate_retrieval_quality(
            [h.chunk.chunk_id for h in hits],
            relevant,
            k=2,
        )
        assert metrics["precision_at_k"] > 0.0
        assert metrics["recall_at_k"] > 0.0
        assert metrics["mrr"] == 1.0
        assert metrics["ndcg_at_k"] > 0.0

        # Edge cases for evaluate_retrieval_quality & cosine_similarity & empty retriever
        assert evaluate_retrieval_quality([], {"c1"})["precision_at_k"] == 0.0
        assert evaluate_retrieval_quality(["c1"], set())["precision_at_k"] == 1.0
        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
        assert HybridFilingRetriever([]).search("anything") == []

    def test_vertex_ai_embedder_fallback_and_mocked_success(self) -> None:
        embedder = VertexAIEmbedder(fallback_dim=64)
        assert embedder.embed([]) == []
        # Fallback path when google.genai raises or lacks credentials
        vecs = embedder.embed(["Revenue increased 10%", ""])
        assert len(vecs) == 2
        assert len(vecs[0]) == 64
        assert all(v == 0.0 for v in vecs[1])

    def test_search_sec_filing_tool_end_to_end(self) -> None:
        res = search_sec_filing(
            "NVDA",
            query="supply chain concentration TSMC foundry",
            form_type="10-K",
            section="risk_factors",
            top_k=2,
        )
        assert res["ticker"] == "NVDA"
        assert res["total_chunks"] >= 1
        assert len(res["matches"]) >= 1
        assert res["citation_id"].startswith("SEC:NVDA:10-K:")

        # Validation errors wrapped by @safe_tool
        bad_form = search_sec_filing("NVDA", query="risk", form_type="DEF 14A")
        assert bad_form["error_type"] == "invalid_argument"
        bad_sec = search_sec_filing("NVDA", query="risk", section="unknown")
        assert bad_sec["error_type"] == "invalid_argument"
        empty_q = search_sec_filing("NVDA", query="   ")
        assert empty_q["error_type"] == "invalid_argument"


# ---------------------------------------------------------------------------
# 3. Circuit Breaker & Cache Telemetry
# ---------------------------------------------------------------------------


class TestCircuitBreakerAndCacheTelemetry:
    def setup_method(self) -> None:
        clear_all_caches()
        reset_all_circuit_breakers()

    def test_circuit_breaker_transitions_closed_open_half_open_closed(self) -> None:
        now = [100.0]
        cb = CircuitBreaker(
            "test_provider",
            failure_threshold=2,
            recovery_timeout=10.0,
            clock=lambda: now[0],
        )
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

        def fail() -> None:
            raise DataProviderError("upstream 503")

        with pytest.raises(DataProviderError):
            cb.call(fail)
        assert cb.state == "CLOSED"

        with pytest.raises(DataProviderError):
            cb.call(fail)
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

        # While OPEN, subsequent calls fast-fail with CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            cb.call(lambda: "should not execute")
        assert exc_info.value.breaker_name == "test_provider"
        assert cb.snapshot()["total_trips"] == 1

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

        cache = TTLCache(maxsize=16, ttl=60.0)
        cache.set("k1", "v1")
        assert cache.get("k1") == (True, "v1")
        assert cache.get("missing") == (False, None)
        stats = cache_stats()
        assert stats["caches_registered"] >= 1


# ---------------------------------------------------------------------------
# 4. Strategy Plugin Registry
# ---------------------------------------------------------------------------


class TestStrategyPluginRegistry:
    def teardown_method(self) -> None:
        unregister_strategy("quality_moat")

    def test_register_list_and_execute_custom_strategy_plugin(self) -> None:
        def _quality_moat_runner(ticker: str) -> StrategySignal:
            return StrategySignal(
                ticker=ticker,
                strategy="quality_moat",
                signal="STRONG_MOAT",
                score=4,
                max_score=4,
                indicators={"roic_pct": 32.5, "gross_margin_pct": 74.0},
                rationale=["ROIC > 20% and gross margin > 60%."],
                as_of="2026-09-15",
            )

        with pytest.raises(ValueError):
            register_strategy("invalid name!", _quality_moat_runner)

        plugin = register_strategy(
            "quality_moat",
            _quality_moat_runner,
            description="High ROIC + gross margin durability screen",
        )
        assert plugin.name == "quality_moat"
        assert is_registered_strategy("quality_moat")
        assert "quality_moat" in list_registered_strategies()

        res = evaluate_strategy("NVDA", "quality_moat")
        assert res["signal"] == "STRONG_MOAT"
        assert res["citation_id"] == "S:NVDA:quality_moat"

        with pytest.raises(KeyError):
            run_registered_strategy("non_existent_strategy", "NVDA")


# ---------------------------------------------------------------------------
# 5. Event-Driven Webhooks & HMAC Signing
# ---------------------------------------------------------------------------


class TestWebhookDispatcher:
    def test_hmac_sign_and_verify(self) -> None:
        body = b'{"event_type":"report.completed","ticker":"NVDA"}'
        ts = "2026-09-15T12:00:00+00:00"
        sig = sign_webhook_payload("top-secret", ts, body)
        assert sig.startswith("sha256=")
        assert verify_webhook_signature("top-secret", ts, body, sig)
        assert not verify_webhook_signature("top-secret", ts, body, "sha256=deadbeef")

    def test_dispatcher_in_process_and_http_delivery(self) -> None:
        received: list[WebhookEvent] = []
        dispatcher = WebhookDispatcher(target_url="https://hooks.example.com/events", secret="sec123")
        dispatcher.subscribe("report.completed", received.append)

        # Also verify a failing subscriber never breaks emission
        def _bad_sub(evt: WebhookEvent) -> None:
            raise RuntimeError("subscriber boom")

        dispatcher.subscribe("*", _bad_sub)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch("analyst.services.webhooks.http.get_client") as mock_get_client:
            mock_get_client.return_value.post.return_value = mock_resp
            evt = dispatcher.emit(
                "report.completed",
                {"report_id": "r1", "tickers": ["NVDA"]},
            )
            mock_get_client.return_value.post.assert_called_once()

        assert len(received) == 1
        assert received[0].event_id == evt.event_id
        assert received[0].to_dict()["event_type"] == "report.completed"


# ---------------------------------------------------------------------------
# 6. DR Snapshot Export / Restore
# ---------------------------------------------------------------------------


class TestDisasterRecoverySnapshots:
    async def test_in_memory_snapshot_roundtrip(self) -> None:
        store = InMemoryReportStore()
        await store.save_report({"report_id": "rep-1", "ticker": "AAPL", "created_at": "2026-01-01T00:00:00+00:00"})
        await store.save_report({"report_id": "rep-2", "ticker": "MSFT", "created_at": "2026-01-02T00:00:00+00:00"})

        snap = await store.export_snapshot()
        assert len(snap) == 2

        new_store = InMemoryReportStore()
        restored = await new_store.restore_snapshot(snap)
        assert restored == 2
        assert (await new_store.get_report("rep-1"))["ticker"] == "AAPL"
        assert (await new_store.get_report("rep-2"))["ticker"] == "MSFT"

    async def test_firestore_snapshot_restore_with_fake_client(self) -> None:
        docs: dict[str, dict[str, Any]] = {}

        class FakeDocRef:
            def __init__(self, doc_id: str) -> None:
                self.id = doc_id

            def set(self, payload: dict[str, Any]) -> None:
                docs[self.id] = dict(payload)

        class FakeCollection:
            def document(self, doc_id: str) -> FakeDocRef:
                return FakeDocRef(doc_id)

        class FakeClient:
            def collection(self, name: str) -> FakeCollection:
                return FakeCollection()

        fs_store = FirestoreReportStore(Settings(), client=FakeClient())
        restored = await fs_store.restore_snapshot([{"report_id": "r-100", "ticker": "GOOGL"}])
        assert restored == 1
        assert docs["r-100"]["ticker"] == "GOOGL"


# ---------------------------------------------------------------------------
# 7. Cost Estimation, Versioned API (/api/v1/*), and /api/metrics
# ---------------------------------------------------------------------------


class _StubAdkRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run_async(self, **kwargs: Any):
        self.calls.append(kwargs)
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1200,
            candidates_token_count=400,
            total_token_count=1600,
        )
        part = types.Part(text="NVDA trades at $128.50.", thought=None)
        yield Event(
            author=FINANCIAL_ANALYST,
            content=types.Content(role="model", parts=[part]),
            partial=False,
            usage_metadata=usage,
        )


class TestApiV1AndMetrics:
    def test_cost_estimation(self) -> None:
        flash_cost = estimate_turn_cost_usd(10_000, 2_000, reasoning_model="gemini-3.8-flash")
        pro_ceiling_cost = estimate_turn_cost_usd(10_000, 2_000, reasoning_model="gemini-pro")
        assert flash_cost > 0
        assert pro_ceiling_cost > flash_cost

    def test_api_v1_routes_dlp_and_metrics_endpoint(self) -> None:
        settings = Settings(
            ENABLE_DLP_REDACTION=True,
            EXPERIMENT_ID="exp-tiering-01",
            EXPERIMENT_VARIANT="flash-specialist",
        )
        store = InMemoryReportStore()
        service = AnalystService(
            settings=settings,
            store=store,
            telemetry=TelemetrySink(settings),
            agent=build_root_agent(settings),
        )
        service.runner = _StubAdkRunner()  # type: ignore[assignment]
        app = create_app(service=service, settings=settings)
        with TestClient(app) as client:
            # Call /api/v1/chat with PII in prompt to verify DLP + v1 routing + metrics
            resp = client.post(
                "/api/v1/chat",
                json={
                    "message": "Analyze NVDA for client john.smith@example.com",
                    "strategy": "momentum",
                    "experiment_variant": "pro-synthesis",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["response"] == "NVDA trades at $128.50."

            # Check persisted report has sanitized prompt, DLP metadata, and cost estimation
            rep = client.get(f"/api/v1/reports/{body['report_id']}")
            assert rep.status_code == 200
            rep_json = rep.json()
            assert "[REDACTED:EMAIL]" in rep_json["prompt"]
            assert rep_json["dlp"]["has_pii"] is True
            assert rep_json["data_classification"] == DataClassification.RESTRICTED_PII_OR_CREDENTIAL
            assert rep_json["estimated_cost_usd"] > 0.0
            assert rep_json["experiment"] == {"id": "exp-tiering-01", "variant": "pro-synthesis"}

            # Check /api/v1/metrics and /api/metrics
            m_resp = client.get("/api/v1/metrics")
            assert m_resp.status_code == 200
            m_data = m_resp.json()
            assert m_data["counters"]["turns_total"] == 1
            assert m_data["counters"]["dlp_redactions"] == 1
            assert m_data["feature_flags"]["dlp_redaction"] is True
            assert "cache" in m_data
            assert "circuit_breakers" in m_data

            # Unknown report returns 404
            assert client.get("/api/v1/reports/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# 8. LLM Ops Metrics (ROUGE/BLEU & Baseline Regression Detection)
# ---------------------------------------------------------------------------


class TestLlmOpsEvaluationEnhancements:
    def test_rouge_bleu_score_case_and_regression_detection(self) -> None:
        from evals.run_evals import aggregate, compare_with_baseline, compute_rouge_and_bleu, score_case

        scores = compute_rouge_and_bleu(
            "Apple FY24 revenue reached $391B with strong Services margin expansion.",
            ["Apple", "FY24", "revenue", "$391B", "Services", "margin"],
        )
        assert scores["rouge_1"] > 0.3
        assert scores["rouge_l"] > 0.2
        assert scores["bleu"] > 0.0
        assert compute_rouge_and_bleu("", ["ref"])["rouge_1"] == 0.0
        assert compute_rouge_and_bleu("cand", [])["rouge_1"] == 1.0

        case = {
            "id": "c1",
            "prompt": "Brief me on NVDA",
            "expected_tools": ["get_stock_quote", "get_financial_metrics"],
            "expected_citation_prefixes": ["Q:NVDA", "M:NVDA"],
            "key_points": ["NVDA", "$128.50", "gross margin"],
        }
        final = {
            "response": "NVDA trades at $128.50 [Q:NVDA] with strong gross margin [M:NVDA].",
            "blocked": False,
            "fact_check": {"accuracy": 1.0, "unverified_numbers": []},
            "tools_called": [
                {"tool": "data_gatherer"},
                {"tool": "get_stock_quote"},
                {"tool": "get_financial_metrics"},
            ],
            "citations": [{"id": "Q:NVDA"}, {"id": "M:NVDA"}],
            "latency": {"time_to_first_thought_ms": 120.0, "total_ms": 450.0},
        }
        res = score_case(case, final, {})
        assert res.tool_recall == 1.0
        assert res.tool_precision == 1.0
        assert res.tool_f1 == 1.0
        assert res.citation_f1 == 1.0
        assert res.rouge_1 > 0.2

        summary = aggregate([res])
        assert compare_with_baseline(summary, summary) == []

        degraded = dict(summary)
        degraded["fact_check_accuracy_mean"] = 0.85
        degraded["ttft_p95_ms"] = 500.0
        regs = compare_with_baseline(degraded, summary)
        assert len(regs) == 2


# ---------------------------------------------------------------------------
# 9. Concurrent Load / SLA Verification
# ---------------------------------------------------------------------------


class TestConcurrentLoadAndSla:
    async def test_concurrent_25_turns_within_latency_sla(self) -> None:
        settings = Settings(ENABLE_DLP_REDACTION=True)
        service = AnalystService(
            settings=settings,
            store=InMemoryReportStore(),
            telemetry=TelemetrySink(settings),
            agent=build_root_agent(settings),
        )
        service.runner = _StubAdkRunner()  # type: ignore[assignment]

        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
        tasks = [
            service.run(
                ChatRequest(
                    message=f"Provide an institutional investment memo for {tickers[i % 5]}",
                    strategy="momentum",
                ),
                UserIdentity(user_id=f"user-{i % 5}"),
            )
            for i in range(25)
        ]
        results = await asyncio.gather(*tasks)
        assert len(results) == 25
        latencies = sorted(r.latency.total_ms for r in results)
        p95 = latencies[int(0.95 * (len(latencies) - 1))]
        assert p95 < 500.0
        snap = service.metrics_snapshot()
        assert snap["counters"]["turns_total"] == 25
        assert snap["counters"]["turns_ok"] == 25

    def test_load_test_cli_runner(self) -> None:
        from scripts.load_test import main

        rc = main(["--concurrency", "10", "--p95-sla-ms", "500"])
        assert rc == 0
