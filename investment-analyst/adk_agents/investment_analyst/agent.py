"""Exposes the production agent tree to ``adk web`` / ``adk run`` / ``adk eval``.

The ADK CLI only puts ``adk_agents/`` on ``sys.path``, so add the backend root
(``investment-analyst/``) to make the ``analyst`` package importable.
"""

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from analyst.agents import build_root_agent  # noqa: E402

root_agent = build_root_agent()
