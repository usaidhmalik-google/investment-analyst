#!/usr/bin/env python3
"""Compatibility adapter for Investment Analyst Agent.

This module delegates directly to the canonical implementation in
`investment-analyst` (`agent.py`, `main.py`, and `tools.py`).
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Add investment-analyst package to sys.path
package_dir = Path(__file__).resolve().parent.parent / "investment-analyst"
if str(package_dir) not in sys.path:
    sys.path.insert(0, str(package_dir))

from agent import (  # noqa: E402
    DEFAULT_AEGIS_URL,
    DEFAULT_MODEL,
    DEFAULT_SESSION_ID,
    INVESTMENT_ANALYST_INSTRUCTION,
    InvestmentAnalystAgent,
    create_genai_client,
    get_gcp_project,
    get_identity_token,
    get_network_context,
)
from main import main  # noqa: E402
from tools import (  # noqa: E402
    EXECUTED_TOOLS,
    OFFLINE_FIXTURES,
    get_company_news,
    get_financial_metrics,
    get_stock_quote,
    get_tool_history,
    reset_tool_history,
)

DEFAULT_PROJECT = get_gcp_project()
DEFAULT_LOCATION = "global"


def run_turn(
    prompt: str,
    aegis_url: str = DEFAULT_AEGIS_URL,
    session_id: str = DEFAULT_SESSION_ID,
    direct: bool = False,
    model: str = DEFAULT_MODEL,
    location: str = DEFAULT_LOCATION,
    project: Optional[str] = None,
    thinking_budget: Optional[int] = None,
    max_output_tokens: int = 4096,
) -> Dict[str, Any]:
    """Execute a single turn using the refactored InvestmentAnalystAgent."""
    agent = InvestmentAnalystAgent(
        aegis_url=aegis_url,
        session_id=session_id,
        direct=direct,
        model=model,
        location=location,
        project=project or DEFAULT_PROJECT,
        thinking_budget=thinking_budget,
        max_output_tokens=max_output_tokens,
    )
    return agent.run(prompt, session_id=session_id)


if __name__ == "__main__":
    main()
