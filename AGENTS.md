# AGENTS.md — guidance for coding agents (Antigravity, Jetski, Gemini CLI, etc.)

Read this before changing anything. It encodes the project's conventions and the
mistakes already made (and fixed) so they are not repeated.

## What this repo is

Multi-agent **Investment Analyst Agent** for MALIK LLC (capstone). Spec of record:
the approved TDD + scope doc (Google Doc "Usaid Malik Capstone - Investment Analyst Agent").
The requirement → code map is in `README.md#design-traceability`.

| Path | What |
| --- | --- |
| `investment-analyst/analyst/` | FastAPI + Google ADK 2.x backend (Python 3.11+) |
| `investment-analyst/tests/` | pytest (fake LLMs + mocked HTTP; never hits network/GCP) |
| `investment-analyst/evals/` | golden dataset + live Gemini eval / LLM-as-a-Judge |
| `frontend/` | React 18 + TS + Tailwind (Vite), nginx container |
| `terraform/analyst/` | all GCP infra for this app |
| `docs/API_CONTRACT.md` | **binding** backend ↔ frontend ↔ infra contract |
| `docs/CAPSTONE_RUBRIC_AND_READOUT.md` | Master FDE Capstone Rubric readout (Personas, CUJs, TCO/ROI, Q&A Defense Matrix, AI Harness, GCP Roadmap) |
| `docs/ARCHITECTURE.md` | System architecture, sequence, data classification, circuit-breaker, and CI/CD diagrams |
| `docs/ADR.md` | Architecture Decision Records (ADRs 001–008) |
| `docs/OPERATIONS_RUNBOOK.md` | Day-2 operations, canary rollout/rollback, incident playbooks, and DR snapshot procedures |
| `docs/FIRST_LIVE_RUN.md` | checklist for the first run against real Gemini / GCP |
| `legacy/`, `aegis-service/`, `terraform/*.tf`, root `tests/` | old Project Aegis prototype — do not modify |

## Definition of done for any change (the "outside the loop" gate)

Iterate until all of these pass — do not hand back work that fails any of them:

```bash
make lint            # ruff format --check + ruff check (backend), eslint + tsc (frontend)
make test            # pytest with --cov-fail-under=80 (currently ~99%), vitest
make tf-validate     # if terraform/ changed
make eval-quick      # if prompts/agents changed and GCP creds exist (deterministic checks)
make eval-all        # before merging prompt/model changes (adds the Gemini judge)
```

If you change the API shape, update `docs/API_CONTRACT.md`, `analyst/api/schemas.py`
and `frontend/src/types.ts` together.

## Architecture invariants (do not break)

1. **Data fetching is deterministic; synthesis is not.** The `financial_analyst` agent has
   **no tools**. It only sees evidence recorded in session state by tools.
2. Every tool goes through `@safe_tool` and records evidence via `record_evidence(...)` with a
   citation id (`Q:`, `H:`, `M:`, `N:`, `SEC:`, `XBRL:`, `S:`). Tools must never raise.
3. Every number in a brief must be traceable to evidence — `guardrails/fact_check.py` verifies it.
   Prompts forbid computing new numbers. If you add a tool, its numeric outputs must be raw numbers
   (not pre-formatted strings) so the fact checker can match them.
4. Strategy signals come from `strategies/engine.py` (pure functions). Never let an LLM decide them.
5. Guardrails run **before** any model call (`guardrails/injection.py`, Model Armor).
6. Config comes from env via `analyst/config.py` only. No hard-coded project ids, models or keys.

## Lessons learned (mistakes made during the build → rules)

| Mistake | Rule |
| --- | --- |
| Nested `call_with_retry` around adapters that already retry → up to 25 attempts per call | Retry in exactly one layer. yfinance is wrapped in `market._yahoo()`; Alpha Vantage/SEC retry internally. |
| FastAPI deps declared as local `Annotated[...]` aliases in a module with `from __future__ import annotations` → every route returned 422 | Keep `Depends` aliases at module level in `api/app.py`. |
| `yfinance` `.news` silently returned `[]` | News falls back Yahoo JSON → Yahoo RSS → Alpha Vantage. Treat empty results as failure (`LookupError`) so fallback triggers. |
| Mutating `tool_context.state["evidence"][k] = v` in place records no ADK state delta | Always re-assign: `state["evidence"] = {**old, k: v}`. |
| ADK 2.x: sub-agents default to `mode="chat"` (transfer targets) | Specialists use `mode="single_turn"` (exposed as tools, run inline, share state). Analyst is a chat sub-agent with `disallow_transfer_to_parent=True` so the next turn returns to the orchestrator. |
| `adk web adk_agents` could not import `analyst` | `adk_agents/investment_analyst/agent.py` adds the backend root to `sys.path`. Keep it. |
| Model Armor `"MATCH_FOUND" in str(x)` also matched `NO_MATCH_FOUND` | Use the anchored regex in `guardrails/model_armor.py`. |
| Gemini 3.x is served from the `global` Vertex endpoint, not `us-central1` (the legacy agent already knew this) | `GOOGLE_CLOUD_LOCATION=global` for models; regional services use `AGENT_ENGINE_LOCATION`/`region`. |
| Client-chosen session ids (not supported by Vertex sessions; hijack risk) | Server always mints session ids. |
| `pkill -f <pattern>` killed the agent's own shell (pattern was in its command line) | Kill by PID, never `pkill -f` with a pattern that appears in your own command. |
| Tests passing with fake LLMs ≠ working with Gemini | After any agent/prompt change, run `make eval-quick`/`eval-all` against real Vertex AI. |
| Aggressive DLP phone/SSN regexes matched substrings inside 18-digit SEC accession numbers (`0000320193-25-000079`) | Always guard numeric PII regexes with `(?<![\d\-])...(?![\d\-])` and Luhn validation (`guardrails/dlp.py`). |
| Static `Literal["momentum", "value", "swing", "income"]` on `StrategySignal.strategy` rejected runtime-registered strategy plugins | Validate `StrategySignal.strategy` with a `@field_validator` delegating to `engine.is_registered_strategy(v)`. |
| Calling `TestClient(app)` without a `with` block skipped FastAPI's `lifespan` hook so `app.state.service` was unset | Always use `with TestClient(app) as client:` when testing routes that resolve `app.state.service`. |
| Unanchored `lib/` in `.gitignore` (from a Python template) silently ignored `frontend/src/lib/` | Explicitly un-ignore `!frontend/src/lib/` in `.gitignore` and verify with `make lint` (`tsc -b`). |
| `fact_check.py` parsed non-currency time-window labels (`3M / 6M Rate of Change`, `3M ROC`) as `$3,000,000` and `$6,000,000` (`M` = million) | Strip non-`$` time-horizon labels (`(?<!\$)\b(?:1|3|6|9|12)M...`) in `guardrails/fact_check.py::_STRIP_PATTERNS` before extracting numeric claims. |
| `opentelemetry-instrumentation-fastapi < 0.65b0` crashed on `OPTIONS` preflight when routes were mounted via `app.include_router(router, prefix=...)` on FastAPI `0.137` (`_IncludedRouter` lacks `.path`) | Register routes directly via `app.add_api_route(f"{prefix}/...", ...)` in `api/app.py` AND pin `opentelemetry-instrumentation-fastapi>=0.65b0` in `requirements.txt`. |
| `requirements.lock` generated on Python 3.12 contains wheels (`numpy==2.5.4`, `pandas==3.1.0`) with `Requires-Python: >=3.12`, which fail on `python:3.11-slim` | Use `python:3.12-slim` in `investment-analyst/Dockerfile` and `cloudbuild.yaml` to match the lockfile's Python version. |
| Custom Cloud Build SA (`investment-analyst-build-sa`) failed `FETCHSOURCE` with HTTP 403 on `<project>_cloudbuild` legacy-ACL bucket | Grant `roles/storage.admin` to `google_service_account.build` in `terraform/analyst/iam.tf` and remove the unexpanded top-level `serviceAccount: projects/$PROJECT_ID/...` from `cloudbuild.yaml`. |
| `COPY --chmod=0755` in `frontend/Dockerfile` failed in Cloud Build (`gcr.io/cloud-builders/docker` runs with BuildKit disabled by default) | Use standard `COPY` followed by `RUN chmod 0755 ...` in `frontend/Dockerfile` so builds succeed with or without BuildKit. |
| Google Front End (GFE) on the downstream `investment-analyst-backend` Cloud Run service (`iap_enabled = false`) strips incoming `X-Goog-IAP-*` and `X-Goog-Authenticated-User-*` headers forwarded by `nginx` → every `/api/*` call returned `401 Missing IAP credentials` | Copy IAP identity headers to `X-Forwarded-IAP-JWT-Assertion`, `X-Forwarded-Authenticated-User-Email`, and `X-Forwarded-Authenticated-User-Id` in `frontend/nginx/backend-proxy.conf` and accept them in `analyst/api/auth.py`. |
| Google Front End (GFE) reserves top-level `/*z` paths (`/healthz`) on `*.run.app` external URLs and returns a GFE 404 before reaching IAP or the container | Keep `/healthz` for Cloud Run's internal kubelet probes (`169.254.169.126:8080/healthz`), and expose `/health`, `/api/health`, `/api/healthz`, and `/api/v1/health` in `analyst/api/app.py` and `frontend/nginx/default.conf.template` for external health checks through IAP. |

**When you hit a new mistake, add a row here in the same change that fixes it.**

## Style

- Python: ruff (config in `investment-analyst/pyproject.toml`), line length 120, type hints,
  Pydantic models for every payload. Async in the service/API layer, sync in data adapters.
- Tests: no network. Use `respx`/`httpx.MockTransport`, the `fake_yf` fixture, and
  `tests/fakes.py::ScriptedLlm` to drive the real ADK agent tree.
- Never commit secrets, `.env`, `*.tfvars`, or `.tools/`/`.venv/`.
