"""Versioned prompt repository."""

from __future__ import annotations

import pytest

from analyst import prompts
from analyst.prompts import (
    PROMPT_NAMES,
    PromptNotFoundError,
    available_versions,
    load_prompt,
    prompt_fingerprint,
    render_prompt,
)


def test_v1_is_available():
    assert "v1" in available_versions()
    assert "__pycache__" not in available_versions()


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_all_prompts_exist_for_v1(name):
    text = load_prompt(name, "v1")
    assert len(text) > 100
    assert "{today}" in text


def test_render_replaces_placeholders():
    text = render_prompt(
        "financial_analyst", "v1", today="2026-09-15", strategy="value", evidence='{"Q:X":{"price":1}}'
    )
    assert "2026-09-15" in text and "Preferred strategy for this session: value." in text
    assert '{"Q:X":{"price":1}}' in text
    assert "{today}" not in text and "{strategy}" not in text and "{evidence}" not in text


def test_render_leaves_unrelated_braces_untouched(tmp_path, monkeypatch):
    (tmp_path / "vt").mkdir()
    (tmp_path / "vt" / "x.md").write_text(
        'Date {today}. JSON: {"a": {"b": 1}} and {unknown} and {{double}}', encoding="utf-8"
    )
    monkeypatch.setattr(prompts, "PROMPT_DIR", tmp_path)
    load_prompt.cache_clear()
    try:
        out = render_prompt("x", "vt", today="T", a="SHOULD_NOT_APPEAR")
        assert out == 'Date T. JSON: {"a": {"b": 1}} and {unknown} and {{double}}'
        assert available_versions() == ["vt"]
    finally:
        load_prompt.cache_clear()


def test_render_without_values_returns_raw():
    assert render_prompt("orchestrator", "v1") == load_prompt("orchestrator", "v1")


def test_missing_prompt_raises():
    with pytest.raises(PromptNotFoundError, match="Prompt 'nope' not found for version 'v1'"):
        load_prompt("nope", "v1")
    with pytest.raises(FileNotFoundError):
        load_prompt("orchestrator", "v999")


def test_fingerprint_stable_and_distinct():
    a = prompt_fingerprint("orchestrator", "v1")
    assert a == prompt_fingerprint("orchestrator", "v1")
    assert len(a) == 12 and all(c in "0123456789abcdef" for c in a)
    assert a != prompt_fingerprint("financial_analyst", "v1")
