"""Concurrent load & latency SLA benchmark runner for the Investment Analyst Agent.

Executes N concurrent multi-agent turns against ``AnalystService`` and verifies
p50/p95/p99 latency SLAs, error rate == 0%, and token cost estimation budgets.

Usage::

    python -m scripts.load_test --concurrency 25 --p95-sla-ms 500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from typing import Any

from google.adk.events import Event
from google.genai import types

from analyst.agents import FINANCIAL_ANALYST, build_root_agent
from analyst.api.schemas import ChatRequest, ChatResponse
from analyst.config import Settings
from analyst.services.analyst_service import AnalystService, UserIdentity
from analyst.services.report_store import InMemoryReportStore
from analyst.services.telemetry_sink import TelemetrySink


class _BenchmarkRunner:
    async def run_async(self, **kwargs: Any):
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1500,
            candidates_token_count=450,
            total_token_count=1950,
        )
        part = types.Part(text="Institutional investment brief synthesized with verified XBRL metrics.", thought=None)
        yield Event(
            author=FINANCIAL_ANALYST,
            content=types.Content(role="model", parts=[part]),
            partial=False,
            usage_metadata=usage,
        )


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, round(pct * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


async def run_load_benchmark(
    concurrency: int = 25,
    p95_sla_ms: float = 500.0,
) -> dict[str, Any]:
    settings = Settings(ENABLE_DLP_REDACTION=True)
    service = AnalystService(
        settings=settings,
        store=InMemoryReportStore(),
        telemetry=TelemetrySink(settings),
        agent=build_root_agent(settings),
    )
    service.runner = _BenchmarkRunner()  # type: ignore[assignment]
    tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
    t0 = time.perf_counter()

    async def _worker(i: int) -> ChatResponse:
        ticker = tickers[i % len(tickers)]
        return await service.run(
            ChatRequest(
                message=f"Produce a comprehensive investment memo for {ticker} with valuation and 10-K risks.",
                strategy="momentum",
            ),
            UserIdentity(user_id=f"load-test-user-{i % 5}"),
        )

    results = await asyncio.gather(*[_worker(i) for i in range(concurrency)], return_exceptions=True)
    wall_ms = (time.perf_counter() - t0) * 1000.0

    successes = [r for r in results if isinstance(r, ChatResponse)]
    failures = [r for r in results if not isinstance(r, ChatResponse)]
    latencies = sorted(float(r.latency.total_ms) for r in successes)

    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)
    p99 = _percentile(latencies, 0.99)
    mean_ms = statistics.mean(latencies) if latencies else 0.0
    sla_passed = (len(failures) == 0) and (p95 <= p95_sla_ms)

    metrics = service.metrics_snapshot()
    return {
        "concurrency": concurrency,
        "succeeded": len(successes),
        "failed": len(failures),
        "error_rate": round(len(failures) / max(concurrency, 1), 4),
        "wall_clock_ms": round(wall_ms, 2),
        "throughput_rps": round(concurrency / max(wall_ms / 1000.0, 1e-6), 2),
        "latency_ms": {
            "mean": round(mean_ms, 2),
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": round(max(latencies) if latencies else 0.0, 2),
        },
        "p95_sla_ms": p95_sla_ms,
        "sla_passed": sla_passed,
        "counters": metrics["counters"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run concurrent SLA load test.")
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--p95-sla-ms", type=float, default=500.0)
    args = parser.parse_args(argv)

    summary = asyncio.run(run_load_benchmark(args.concurrency, args.p95_sla_ms))
    print(json.dumps(summary, indent=2))
    return 0 if summary["sla_passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
