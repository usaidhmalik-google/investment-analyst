"""Pre-flight check for a live environment: credentials, Vertex AI models, data providers.

Run before the first live eval/deploy:

    cd investment-analyst && ../.venv/bin/python scripts/preflight.py

Each check prints PASS/FAIL with the fix. Exits non-zero if anything required fails.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, required: bool = True):
    def deco(fn):
        def run():
            started = time.perf_counter()
            try:
                detail = fn() or ""
                RESULTS.append((name, True, f"{detail} ({(time.perf_counter() - started) * 1000:.0f} ms)"))
            except Exception as exc:  # noqa: BLE001 - report every failure
                RESULTS.append((name, not required, f"{'FAIL' if required else 'WARN'}: {exc}"))

        return run

    return deco


def main() -> int:
    from analyst.config import get_settings

    settings = get_settings()
    print(f"project={settings.google_cloud_project} location={settings.google_cloud_location}")
    print(f"router={settings.router_model} reasoning={settings.reasoning_model} judge={settings.judge_model}\n")

    @check("Application Default Credentials")
    def adc():
        import google.auth

        _, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not (settings.google_cloud_project or project):
            raise RuntimeError("No project: set GOOGLE_CLOUD_PROJECT")
        return f"ADC project={project}"

    @check("GOOGLE_GENAI_USE_VERTEXAI=TRUE")
    def vertex_flag():
        if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() not in ("TRUE", "1"):
            raise RuntimeError("export GOOGLE_GENAI_USE_VERTEXAI=TRUE (otherwise ADK expects a Gemini API key)")

    def model_check(model: str):
        from google import genai

        client = genai.Client(
            vertexai=True, project=settings.google_cloud_project, location=settings.google_cloud_location
        )
        resp = client.models.generate_content(model=model, contents="Reply with the single word: ok")
        return f"{model} → {(resp.text or '').strip()[:20]!r}"

    @check("Yahoo Finance quote (live)", required=False)
    def yahoo():
        from analyst.data import yahoo as y

        q = y.fetch_quote("NVDA")
        return f"NVDA {q.price} via {q.source} — if this fails on Cloud Run, configure Alpha Vantage"

    @check("Yahoo RSS news (live)", required=False)
    def rss():
        from analyst.data import yahoo as y

        return f"{len(y.fetch_news_rss('NVDA', 3).articles)} articles"

    @check("SEC EDGAR (live, User-Agent)", required=False)
    def sec():
        from analyst.data import sec_edgar

        if "example" in settings.sec_user_agent:
            raise RuntimeError("Set SEC_USER_AGENT to a real contact, e.g. 'MALIK LLC Analyst you@google.com'")
        return f"NVDA CIK {sec_edgar.resolve_cik('NVDA')[0]}"

    @check("Alpha Vantage fallback configured", required=False)
    def av():
        from analyst.data.secrets import get_alpha_vantage_key

        if not get_alpha_vantage_key():
            raise RuntimeError("No ALPHA_VANTAGE_API_KEY / ALPHA_VANTAGE_SECRET — Yahoo is the only market provider")
        return "key available"

    if settings.session_backend == "vertex":

        @check("Vertex AI Agent Engine sessions")
        def sessions():
            import asyncio

            from analyst.services.sessions import build_session_service

            svc = build_session_service(settings)
            s = asyncio.run(svc.create_session(app_name="investment_analyst", user_id="preflight"))
            asyncio.run(svc.delete_session(app_name="investment_analyst", user_id="preflight", session_id=s.id))
            return f"created/deleted {s.id}"

    else:
        sessions = None

    adc()
    vertex_flag()
    for label, model in (
        ("router model", settings.router_model),
        ("reasoning model", settings.reasoning_model),
        ("judge model", settings.judge_model),
    ):
        check(f"Vertex AI {label} ({model} @ {settings.google_cloud_location})")(lambda m=model: model_check(m))()
    for fn in (yahoo, rss, sec, av):
        fn()
    if sessions:
        sessions()

    width = max(len(n) for n, _, _ in RESULTS)
    failed = False
    for name, ok, detail in RESULTS:
        failed |= not ok
        status = "FAIL" if not ok else ("WARN" if detail.startswith("WARN") else "PASS")
        print(f"{status:4}  {name:<{width}}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
