"""Versioned prompt repository.

Prompts live in ``analyst/prompts/<version>/<name>.md`` and are loaded at runtime
based on ``PROMPT_VERSION`` (TDD: prompts are stored in a versioned repository and
loaded dynamically). Placeholders use ``{name}`` and are substituted with plain string
replacement so JSON braces inside prompts are never misinterpreted.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent
PROMPT_NAMES = ("orchestrator", "data_gatherer", "sec_filing_parser", "strategy_evaluator", "financial_analyst")


class PromptNotFoundError(FileNotFoundError):
    pass


def available_versions() -> list[str]:
    return sorted(p.name for p in PROMPT_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))


@lru_cache(maxsize=64)
def load_prompt(name: str, version: str) -> str:
    path = PROMPT_DIR / version / f"{name}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"Prompt '{name}' not found for version '{version}' ({path})")
    return path.read_text(encoding="utf-8")


def prompt_fingerprint(name: str, version: str) -> str:
    """Short content hash logged with each run for prompt lineage."""
    return hashlib.sha256(load_prompt(name, version).encode()).hexdigest()[:12]


def render_prompt(name: str, version: str, **values: str) -> str:
    text = load_prompt(name, version)
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text
