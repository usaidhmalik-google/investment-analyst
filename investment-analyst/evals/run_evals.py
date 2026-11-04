"""Golden-dataset regression evaluation (``make eval-all``).

Runs every golden case through the real multi-agent system (Gemini on Vertex AI) over
deterministic offline market fixtures, then scores each answer with:

* deterministic checks — numeric fact-check accuracy, tool precision/recall/F1, citation
  precision/recall/F1, ROUGE-1 / ROUGE-2 / ROUGE-L / BLEU lexical overlap against expected
  key points, guardrail behaviour, latency (time to first thought / token);
* LLM-as-a-Judge (Gemini Flash) — faithfulness, explanation quality, thematic
  consistency, citation coverage and safety;
* automated regression detection against a baseline JSON scorecard (``--baseline``).

The golden dataset is read from ``evals/golden/golden_dataset.jsonl`` or, with
``--bq-table project.dataset.table``, from BigQuery. Exits non-zero when any quality
gate or regression check fails so it can block deployment in CI.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

GATES = {
    "fact_check_accuracy_min": 1.0,  # North Star: 100% numeric agreement
    "judge_faithfulness_min": 4.0,
    "judge_mean_min": 4.0,
    "tool_recall_min": 0.9,
    "guardrail_pass_rate_min": 1.0,
    "ttft_p95_ms_max": 6000.0,  # TDD: p95 "Time to First Thought" <= 6.0 s
}

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.%$\-]*")


def _tokenize_eval(text: str) -> list[str]:
    return [tok.lower() for tok in _WORD_RE.findall(text or "")]


def _f1(precision: float, recall: float) -> float:
    return (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0


def _lcs_length(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    # Bound sequence length for fast DP on long briefs
    a_bounded, b_bounded = a[:512], b[:512]
    dp = [0] * (len(b_bounded) + 1)
    for tok_a in a_bounded:
        prev = 0
        for j, tok_b in enumerate(b_bounded, start=1):
            temp = dp[j]
            if tok_a == tok_b:
                dp[j] = prev + 1
            elif dp[j - 1] > dp[j]:
                dp[j] = dp[j - 1]
            prev = temp
    return dp[-1]


def compute_rouge_and_bleu(candidate: str, reference: list[str] | str) -> dict[str, float]:
    """Compute deterministic ROUGE-1 F1, ROUGE-2 F1, ROUGE-L F1, and smoothed BLEU-4."""
    ref_text = " ".join(reference) if isinstance(reference, list) else str(reference or "")
    cand_tokens = _tokenize_eval(candidate)
    ref_tokens = _tokenize_eval(ref_text)
    if not ref_tokens:
        return {"rouge_1": 1.0, "rouge_2": 1.0, "rouge_l": 1.0, "bleu": 1.0}
    if not cand_tokens:
        return {"rouge_1": 0.0, "rouge_2": 0.0, "rouge_l": 0.0, "bleu": 0.0}

    # ROUGE-1
    cand_1 = Counter(cand_tokens)
    ref_1 = Counter(ref_tokens)
    overlap_1 = sum((cand_1 & ref_1).values())
    r1_p = overlap_1 / len(cand_tokens)
    r1_r = overlap_1 / len(ref_tokens)
    rouge_1 = _f1(r1_p, r1_r)

    # ROUGE-2
    if len(cand_tokens) >= 2 and len(ref_tokens) >= 2:
        cand_2 = Counter(zip(cand_tokens[:-1], cand_tokens[1:], strict=True))
        ref_2 = Counter(zip(ref_tokens[:-1], ref_tokens[1:], strict=True))
        overlap_2 = sum((cand_2 & ref_2).values())
        r2_p = overlap_2 / max(1, len(cand_tokens) - 1)
        r2_r = overlap_2 / max(1, len(ref_tokens) - 1)
        rouge_2 = _f1(r2_p, r2_r)
    else:
        rouge_2 = rouge_1

    # ROUGE-L (Longest Common Subsequence)
    lcs = _lcs_length(cand_tokens, ref_tokens)
    rl_p = lcs / len(cand_tokens)
    rl_r = lcs / len(ref_tokens)
    rouge_l = _f1(rl_p, rl_r)

    # Smoothed BLEU-4 (Chen & Cherry add-1 smoothing for n>=2)
    precisions: list[float] = []
    max_n = min(4, len(cand_tokens), len(ref_tokens))
    for n in range(1, max_n + 1):
        c_ngrams = Counter(tuple(cand_tokens[i : i + n]) for i in range(len(cand_tokens) - n + 1))
        r_ngrams = Counter(tuple(ref_tokens[i : i + n]) for i in range(len(ref_tokens) - n + 1))
        matches = sum((c_ngrams & r_ngrams).values())
        total = max(1, len(cand_tokens) - n + 1)
        if n == 1:
            p_n = (matches + 1e-9) / (total + 1e-9)
        else:
            p_n = (matches + 1.0) / (total + 1.0)
        precisions.append(p_n)

    geo_mean = math.exp(sum(math.log(p) for p in precisions) / len(precisions)) if precisions else 0.0
    bp = 1.0 if len(cand_tokens) >= len(ref_tokens) else math.exp(1.0 - len(ref_tokens) / len(cand_tokens))
    bleu = bp * geo_mean

    return {
        "rouge_1": round(rouge_1, 4),
        "rouge_2": round(rouge_2, 4),
        "rouge_l": round(rouge_l, 4),
        "bleu": round(bleu, 4),
    }


@dataclass
class CaseResult:
    id: str
    prompt: str
    response: str
    blocked: bool
    fact_check_accuracy: float
    unverified_numbers: list[str]
    tools_called: list[str]
    tool_recall: float
    citation_recall: float
    guardrail_pass: bool | None
    ttft_ms: float | None
    total_ms: float
    judge: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tool_precision: float = 1.0
    tool_f1: float = 1.0
    citation_precision: float = 1.0
    citation_f1: float = 1.0
    rouge_1: float = 0.0
    rouge_2: float = 0.0
    rouge_l: float = 0.0
    bleu: float = 0.0


def load_cases(path: Path | None = None, bq_table: str | None = None) -> list[dict[str, Any]]:
    if bq_table:
        from google.cloud import bigquery

        client = bigquery.Client()
        rows = client.query(f"SELECT * FROM `{bq_table}`").result()
        cases = []
        for row in rows:
            case = dict(row.items())
            for key in ("tickers", "expected_tools", "expected_citation_prefixes", "key_points", "must_not"):
                value = case.get(key)
                if isinstance(value, str):
                    case[key] = json.loads(value)
            cases.append(case)
        return cases
    path = path or HERE / "golden" / "golden_dataset.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def score_case(case: dict[str, Any], final: dict[str, Any], evidence: dict[str, Any], judge=None) -> CaseResult:
    tools = [t["tool"] for t in final.get("tools_called", [])]
    expected_tools = case.get("expected_tools") or []
    tool_recall = 1.0 if not expected_tools else sum(t in tools for t in expected_tools) / len(expected_tools)
    if not expected_tools:
        tool_precision = 1.0
    elif not tools:
        tool_precision = 0.0
    else:
        # Exclude orchestrator sub-agent delegation wrappers when computing leaf tool precision
        leaf_tools = [
            t for t in tools if t not in {"data_gatherer", "sec_filing_parser", "strategy_evaluator"}
        ] or tools
        tool_precision = sum(t in expected_tools for t in leaf_tools) / len(leaf_tools)
    tool_f1 = _f1(tool_precision, tool_recall)

    cited = [c["id"] for c in final.get("citations", [])]
    prefixes = case.get("expected_citation_prefixes") or []
    citation_recall = (
        1.0 if not prefixes else sum(any(c.startswith(p) for c in cited) for p in prefixes) / len(prefixes)
    )
    if not prefixes:
        citation_precision = 1.0
    elif not cited:
        citation_precision = 0.0
    else:
        citation_precision = sum(any(c.startswith(p) for p in prefixes) for c in cited) / len(cited)
    citation_f1 = _f1(citation_precision, citation_recall)

    lexical = compute_rouge_and_bleu(final.get("response", ""), case.get("key_points") or [])

    guardrail_pass = None
    if case.get("expect_blocked"):
        guardrail_pass = bool(final.get("blocked")) and not tools
    result = CaseResult(
        id=case["id"],
        prompt=case["prompt"],
        response=final.get("response", ""),
        blocked=bool(final.get("blocked")),
        fact_check_accuracy=final["fact_check"]["accuracy"],
        unverified_numbers=final["fact_check"]["unverified_numbers"],
        tools_called=tools,
        tool_recall=round(tool_recall, 3),
        tool_precision=round(tool_precision, 3),
        tool_f1=round(tool_f1, 3),
        citation_recall=round(citation_recall, 3),
        citation_precision=round(citation_precision, 3),
        citation_f1=round(citation_f1, 3),
        rouge_1=lexical["rouge_1"],
        rouge_2=lexical["rouge_2"],
        rouge_l=lexical["rouge_l"],
        bleu=lexical["bleu"],
        guardrail_pass=guardrail_pass,
        ttft_ms=final["latency"].get("time_to_first_thought_ms"),
        total_ms=final["latency"]["total_ms"],
    )
    if judge is not None:
        scores = judge.score(
            prompt=case["prompt"],
            response=result.response,
            evidence=evidence,
            key_points=case.get("key_points") or [],
            must_not=case.get("must_not") or [],
        )
        result.judge = {**scores.model_dump(), "mean": scores.mean}
    return result


def p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def aggregate(results: list[CaseResult]) -> dict[str, Any]:
    ok = [r for r in results if r.error is None]
    judged = [r for r in ok if r.judge]
    guardrails = [r for r in ok if r.guardrail_pass is not None]
    ttfts = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    summary = {
        "cases": len(results),
        "errors": len(results) - len(ok),
        "fact_check_accuracy_mean": round(statistics.fmean([r.fact_check_accuracy for r in ok]), 4) if ok else 0.0,
        "tool_recall_mean": round(statistics.fmean([r.tool_recall for r in ok]), 3) if ok else 0.0,
        "tool_precision_mean": round(statistics.fmean([r.tool_precision for r in ok]), 3) if ok else 0.0,
        "tool_f1_mean": round(statistics.fmean([r.tool_f1 for r in ok]), 3) if ok else 0.0,
        "citation_recall_mean": round(statistics.fmean([r.citation_recall for r in ok]), 3) if ok else 0.0,
        "citation_precision_mean": round(statistics.fmean([r.citation_precision for r in ok]), 3) if ok else 0.0,
        "citation_f1_mean": round(statistics.fmean([r.citation_f1 for r in ok]), 3) if ok else 0.0,
        "rouge_1_mean": round(statistics.fmean([r.rouge_1 for r in ok]), 4) if ok else 0.0,
        "rouge_2_mean": round(statistics.fmean([r.rouge_2 for r in ok]), 4) if ok else 0.0,
        "rouge_l_mean": round(statistics.fmean([r.rouge_l for r in ok]), 4) if ok else 0.0,
        "bleu_mean": round(statistics.fmean([r.bleu for r in ok]), 4) if ok else 0.0,
        "guardrail_pass_rate": round(sum(r.guardrail_pass for r in guardrails) / len(guardrails), 3)
        if guardrails
        else 1.0,
        "ttft_p95_ms": p95(ttfts),
        "total_ms_p95": p95([r.total_ms for r in ok]),
    }
    if judged:
        for key in (
            "faithfulness",
            "explanation_quality",
            "thematic_consistency",
            "citation_coverage",
            "safety",
            "mean",
        ):
            summary[f"judge_{key}"] = round(statistics.fmean([r.judge[key] for r in judged]), 3)
    return summary


def compare_with_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    tolerance: float = 0.02,
    latency_tolerance_pct: float = 0.15,
) -> list[str]:
    """Detect quality or latency regressions relative to a prior baseline summary."""
    regressions: list[str] = []
    higher_is_better = (
        "fact_check_accuracy_mean",
        "tool_recall_mean",
        "tool_f1_mean",
        "citation_recall_mean",
        "citation_f1_mean",
        "guardrail_pass_rate",
        "rouge_l_mean",
        "bleu_mean",
        "judge_faithfulness",
        "judge_mean",
    )
    for key in higher_is_better:
        if key in current and key in baseline and current[key] is not None and baseline[key] is not None:
            drop = float(baseline[key]) - float(current[key])
            if drop > tolerance:
                regressions.append(
                    f"regression in {key}: current {current[key]} < baseline {baseline[key]} (drop {drop:.4f} > {tolerance})"
                )
    if current.get("ttft_p95_ms") is not None and baseline.get("ttft_p95_ms"):
        base_ttft = float(baseline["ttft_p95_ms"])
        cur_ttft = float(current["ttft_p95_ms"])
        if base_ttft > 0 and (cur_ttft - base_ttft) / base_ttft > latency_tolerance_pct:
            regressions.append(
                f"latency regression in ttft_p95_ms: current {cur_ttft}ms > baseline {base_ttft}ms"
            )
    return regressions


def check_gates(summary: dict[str, Any], judged: bool) -> list[str]:
    failures = []
    if summary["errors"]:
        failures.append(f"{summary['errors']} case(s) errored")
    if summary["fact_check_accuracy_mean"] < GATES["fact_check_accuracy_min"]:
        failures.append(
            f"fact-check accuracy {summary['fact_check_accuracy_mean']} < {GATES['fact_check_accuracy_min']}"
        )
    if summary["tool_recall_mean"] < GATES["tool_recall_min"]:
        failures.append(f"tool recall {summary['tool_recall_mean']} < {GATES['tool_recall_min']}")
    if summary["guardrail_pass_rate"] < GATES["guardrail_pass_rate_min"]:
        failures.append(f"guardrail pass rate {summary['guardrail_pass_rate']} < {GATES['guardrail_pass_rate_min']}")
    if summary["ttft_p95_ms"] is not None and summary["ttft_p95_ms"] > GATES["ttft_p95_ms_max"]:
        failures.append(f"TTFT p95 {summary['ttft_p95_ms']}ms > {GATES['ttft_p95_ms_max']}ms")
    if judged:
        if summary["judge_faithfulness"] < GATES["judge_faithfulness_min"]:
            failures.append(f"judge faithfulness {summary['judge_faithfulness']} < {GATES['judge_faithfulness_min']}")
        if summary["judge_mean"] < GATES["judge_mean_min"]:
            failures.append(f"judge mean {summary['judge_mean']} < {GATES['judge_mean_min']}")
    return failures


def render_scorecard(
    summary: dict[str, Any], results: list[CaseResult], failures: list[str], meta: dict[str, Any]
) -> str:
    lines = [
        "# Investment Analyst — Golden Dataset Scorecard",
        "",
        f"- Run: {meta['timestamp']}",
        f"- Models: router `{meta['router_model']}`, reasoning `{meta['reasoning_model']}`, judge `{meta['judge_model']}`",
        f"- Prompt version: `{meta['prompt_version']}`; data: offline fixtures (as of 2026-09-15)",
        f"- Result: **{'PASS' if not failures else 'FAIL'}**",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    lines += [f"| {k} | {v} |" for k, v in summary.items()]
    if failures:
        lines += ["", "## Gate failures", ""] + [f"- {f}" for f in failures]
    lines += [
        "",
        "## Cases",
        "",
        "| Case | Fact-check | Tool recall | Tool F1 | Citation recall | ROUGE-L | BLEU | Guardrail | TTFT ms | Judge mean | Error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r.id} | {r.fact_check_accuracy} | {r.tool_recall} | {r.tool_f1} | {r.citation_recall} | "
            f"{r.rouge_l} | {r.bleu} | {'' if r.guardrail_pass is None else r.guardrail_pass} | "
            f"{r.ttft_ms} | {r.judge.get('mean', '')} | {r.error or ''} |"
        )
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    os.environ["ANALYST_OFFLINE_MODE"] = "true"  # deterministic historical market conditions
    from analyst.api.schemas import ChatRequest
    from analyst.config import get_settings
    from analyst.services.analyst_service import APP_NAME, AnalystService, UserIdentity
    from analyst.services.report_store import InMemoryReportStore
    from analyst.services.telemetry_sink import TelemetrySink
    from analyst.tools.evidence import get_evidence

    get_settings.cache_clear()
    settings = get_settings()
    service = AnalystService(settings=settings, store=InMemoryReportStore(), telemetry=TelemetrySink(settings))
    judge = None
    if not args.no_judge:
        from judge import GeminiJudge

        judge = GeminiJudge(
            settings.judge_model, settings.google_cloud_project, args.judge_location or settings.google_cloud_location
        )

    cases = load_cases(Path(args.dataset) if args.dataset else None, args.bq_table)
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    user = UserIdentity(user_id="eval-runner", email="eval-runner")
    results: list[CaseResult] = []
    for case in cases:
        started = time.perf_counter()
        try:
            final = (
                await service.run(ChatRequest(message=case["prompt"], strategy=case.get("strategy")), user)
            ).model_dump()
            session = await service.session_service.get_session(
                app_name=APP_NAME, user_id=user.user_id, session_id=final["session_id"]
            )
            evidence = get_evidence(session.state if session else {})
            result = score_case(case, final, evidence, judge)
        except Exception as exc:
            result = CaseResult(
                id=case["id"], prompt=case["prompt"], response="", blocked=False, fact_check_accuracy=0.0,
                unverified_numbers=[], tools_called=[], tool_recall=0.0, citation_recall=0.0, guardrail_pass=None,
                ttft_ms=None, total_ms=(time.perf_counter() - started) * 1000, error=repr(exc),
            )  # fmt: skip
        results.append(result)
        print(
            f"[{result.id}] fact={result.fact_check_accuracy} tools={result.tool_recall} judge={result.judge.get('mean')} err={result.error}"
        )

    summary = aggregate(results)
    failures = check_gates(summary, judged=judge is not None)
    if getattr(args, "baseline", None):
        baseline_payload = json.loads(Path(args.baseline).read_text())
        baseline_summary = baseline_payload.get("summary", baseline_payload)
        failures.extend(compare_with_baseline(summary, baseline_summary))
    meta = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "router_model": settings.router_model,
        "reasoning_model": settings.reasoning_model,
        "judge_model": settings.judge_model if judge else "disabled",
        "prompt_version": settings.prompt_version,
    }
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"eval_results_{stamp}.json").write_text(
        json.dumps(
            {"meta": meta, "summary": summary, "failures": failures, "cases": [r.__dict__ for r in results]},
            indent=2,
            default=str,
        )
    )
    (out_dir / f"SCORECARD_{stamp}.md").write_text(render_scorecard(summary, results, failures, meta))
    print(json.dumps({"summary": summary, "failures": failures}, indent=2))
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", help="Path to a JSONL golden dataset")
    parser.add_argument("--bq-table", help="Load the golden dataset from BigQuery (project.dataset.table)")
    parser.add_argument("--case", action="append", help="Run only the given case id (repeatable)")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM-as-a-Judge scoring")
    parser.add_argument("--judge-location", help="Vertex AI location for the judge model (e.g. global)")
    parser.add_argument("--baseline", help="Optional baseline eval_results JSON file for regression detection")
    parser.add_argument("--output-dir", default=str(HERE / "results"))
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
