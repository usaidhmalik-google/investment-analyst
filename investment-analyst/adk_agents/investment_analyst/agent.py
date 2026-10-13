"""Exposes the production agent tree to ``adk web`` / ``adk run`` / ``adk eval``."""

from analyst.agents import build_root_agent

root_agent = build_root_agent()
