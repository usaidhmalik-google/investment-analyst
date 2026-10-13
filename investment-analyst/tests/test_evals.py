"""Golden-dataset eval harness logic (deterministic parts + judge plumbing with a fake judge)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

import run_evals
from judge import JudgeScores, build_judge_prompt


class FakeJudge:
    def __init__(self, score: int = 5):
        self.calls = []
        self.value = score

    def score(self, **kwargs):
        self.calls.append(kwargs)
        v = self.value
        return JudgeScores(faithfulness=v, explanation_quality=v, thematic_consistency=v, citation_coverage=v, safety=v)


def _final(**overrides):
    base = {
        "response": "NVDA trades at $128.50 [Q:NVDA]",
        "blocked": False,
        "fact_check": {"accuracy": 1.0, "unverified_numbers": []},
        "tools_called": [{"agent": "data_gatherer", "tool": "get_stock_quote", "args": {"ticker": "NVDA"}}],
        "citations": [{"id": "Q:NVDA"}],
        "latency": {"time_to_first_thought_ms": 900.0, "total_ms": 4000.0},
    }
    base.update(overrides)
    return base


def test_golden_dataset_loads_and_is_well_formed():
    cases = run_evals.load_cases()
    assert len(cases) >= 8
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case["prompt"] and isinstance(case["key_points"], list)


def test_score_case_recalls_and_judge():
    case = {
        "id": "c1",
        "prompt": "p",
        "expected_tools": ["get_stock_quote", "get_company_news"],
        "expected_citation_prefixes": ["Q:NVDA", "N:NVDA"],
        "key_points": ["k"],
        "must_not": [],
    }
    judge = FakeJudge(4)
    result = run_evals.score_case(case, _final(), {"Q:NVDA": {}}, judge)
    assert result.tool_recall == 0.5
    assert result.citation_recall == 0.5
    assert result.guardrail_pass is None
    assert result.judge["mean"] == 4.0
    assert judge.calls[0]["key_points"] == ["k"]


def test_guardrail_case_requires_block_and_no_tools():
    case = {"id": "g", "prompt": "buy", "expect_blocked": True}
    assert run_evals.score_case(case, _final(blocked=True, tools_called=[]), {}).guardrail_pass is True
    assert run_evals.score_case(case, _final(blocked=False), {}).guardrail_pass is False


def test_aggregate_gates_and_scorecard():
    good = run_evals.score_case({"id": "a", "prompt": "p"}, _final(), {}, FakeJudge(5))
    bad = run_evals.score_case(
        {"id": "b", "prompt": "p"},
        _final(
            fact_check={"accuracy": 0.5, "unverified_numbers": ["$1"]},
            latency={"time_to_first_thought_ms": 9000.0, "total_ms": 9500.0},
        ),
        {},
        FakeJudge(2),
    )
    summary = run_evals.aggregate([good, bad])
    assert summary["fact_check_accuracy_mean"] == 0.75
    assert summary["ttft_p95_ms"] == 9000.0
    failures = run_evals.check_gates(summary, judged=True)
    assert any("fact-check" in f for f in failures)
    assert any("TTFT" in f for f in failures)
    assert any("judge mean" in f for f in failures)
    assert run_evals.check_gates(run_evals.aggregate([good]), judged=True) == []
    card = run_evals.render_scorecard(
        summary,
        [good, bad],
        failures,
        {"timestamp": "t", "router_model": "r", "reasoning_model": "m", "judge_model": "j", "prompt_version": "v1"},
    )
    assert "FAIL" in card and "| a |" in card


def test_p95_and_judge_prompt():
    assert run_evals.p95([]) is None
    assert run_evals.p95([1.0, 2.0, 3.0]) == 3.0
    prompt = build_judge_prompt("q", "resp", {"Q:NVDA": {"price": 1}}, ["kp"], ["mn"])
    assert "resp" in prompt and "- kp" in prompt and "- mn" in prompt and '"Q:NVDA"' in prompt
