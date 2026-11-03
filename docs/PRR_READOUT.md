# Product Readiness Review (PRR) readout: Investment Analyst Agent

**Customer:** MALIK LLC · **Engagement:** Onboarding Project 2 (financial domain) · **Environment:** Argolis sandbox `fde-investment-analyst-sandbox-dev`

This document is the Sprint 6 readout. Each item marks whether it is **verified** (by automated tests or static checks in this repo) or **pending live validation**, meaning it needs the sandbox project, Vertex AI credentials or a deployment to confirm.

## 1. Scope delivered

| Scope deliverable | Status | Evidence |
| --- | --- | --- |
| Conversational multi-agent architecture with intent routing | Verified offline | `analyst/agents/`; `tests/test_end_to_end.py` drives the real ADK tree with scripted models |
| External API tools with rate limiting and retry | Verified offline; live data spot-checked | `analyst/data/`, `analyst/tools/resilience.py`; adapter tests use mocked HTTP. A manual live run against Yahoo and SEC EDGAR returned real data. |
| Agentic synthesis and grounding | Verified offline | Evidence registry, grounding-lock prompt, `guardrails/fact_check.py` |
| Security: service accounts, Secret Manager, least-privilege IAM | Static validation | `terraform/analyst/` (`terraform validate`) |
| Observability: OpenTelemetry + Cloud Trace | Verified offline; export pending | `analyst/telemetry.py`; Cloud Trace export needs `ENABLE_CLOUD_TRACE=true` on Cloud Run |
| pytest suite > 80% coverage with mocked LLM and APIs | Verified | 600+ tests, about 99% line coverage; gate enforced in `cloudbuild.yaml` |
| React frontend | Verified | Vitest, ESLint, tsc and the production build all pass |
| Docker, Terraform, CI/CD, Cloud Run | Static validation; deploy pending | Dockerfiles, `terraform/analyst`, `cloudbuild.yaml` |

## 2. Definition of Done scorecard

| Criterion (scope) | Target | How it's measured | Status |
| --- | --- | --- | --- |
| Numeric accuracy in narrative | 100% | Fact checker on every response; `make eval-all` gates on mean = 1.0 | Mechanism verified; **live score pending** |
| Minimise hallucinations | Strict grounding | Grounding lock, fact check, judge `faithfulness` ≥ 4 | **Pending live eval** |
| Time to First Thought | < 4.0 s (scope) / p95 ≤ 6.0 s (TDD) | `latency.time_to_first_thought_ms` per response; eval gate | **Pending live eval**; target needs to be agreed |
| Multi-strategy signal accuracy | 100% | Deterministic engine; 84 boundary and branch tests | Verified |
| SEC ingestion quality | Zero parsing failures on 10-K/10-Q | Extraction never raises; table-of-contents skipping tested; live NVDA 10-K and AAPL 10-Q sections extracted | Verified (spot-checked live) |
| Containerised, Terraform-provisioned, on Cloud Run | Deployed | `terraform apply` + Cloud Build | **Pending deployment** |
| OTEL + Cloud Trace + operational logging | Configured | Structured JSON logs with trace correlation, FastAPI + ADK spans | Verified locally; **export pending** |

## 3. Security review

* **AuthN:** IAP on the frontend Cloud Run service. The backend verifies the IAP JWT (`REQUIRE_IAP=true`) and accepts only internal ingress. You can turn the backend's Cloud Run invoker check back on (`frontend_attach_id_token = true`, `backend_invoker_iam_disabled = false`).
* **AuthZ:** `roles/iap.httpsResourceAccessor` for one Cloud Identity group. Each runtime and build identity has its own SA with narrow roles. Secret access is granted per secret.
* **Secrets:** the Alpha Vantage key lives in Secret Manager. Terraform creates the secret, not its value. There are no keys in images or the repo.
* **Data:** public market data only. TLS in transit. Data at rest is encrypted with Google-managed keys (GMEK); the CMEK option is documented.
* **AI safety:** a local injection, trade-execution and length screen runs before any model call. Model Armor screens prompts and responses when configured. Specialists treat tool and news content as data. The analyst cannot execute trades and has no tools.
* **Audit:** every chat and feedback action is written to `analyst_telemetry.audit_log` (user, tickers, report id, status). Reports, with prompt lineage, are stored in Firestore.
* **Session isolation:** session ids are minted by the server. Ids that are unknown or belong to another user are never reused.

## 4. Operations runbook

| Task | How |
| --- | --- |
| Deploy | Merge to `main`. The Cloud Build trigger runs lint, tests, build, push and `gcloud run deploy`. |
| Roll back | `gcloud run services update-traffic investment-analyst-backend --to-revisions=<prev>=100 --region us-central1` (same for the frontend) |
| Change models | Set the `ANALYST_ROUTER_MODEL` / `ANALYST_REASONING_MODEL` Terraform variables, then apply |
| Change prompts | Add `analyst/prompts/vN`, set `PROMPT_VERSION=vN`, run `make eval-all` before rollout |
| Rotate the Alpha Vantage key | `gcloud secrets versions add alpha-vantage-api-key --data-file=-`. It's picked up on the next instance start. |
| Investigate a bad answer | Find the `report_id` in Firestore (prompt, response, citations, fact check, tools, prompt hashes), then look up the trace in Cloud Trace via the log's `logging.googleapis.com/trace` |
| Cost and latency | BigQuery `analyst_telemetry.usage_events` (tokens, TTFT, total ms per report) |

Suggested alerts (not yet provisioned): 5xx rate on the backend, `fact_check.accuracy < 1` log-based metric, TTFT p95 above target, and the Model Armor unavailable warning.

## 5. Risks and open decisions

1. **Latency target:** the TDD says p95 ≤ 6.0 s and the scope says < 4.0 s. Agree on one; the eval gate uses 6.0 s.
2. **Model versions:** the defaults follow the TDD (Gemini 2.5 Pro / 3.5 Flash). Earlier Aegis benchmarks favoured 3.1 Pro. This is a config-only swap.
3. **Data provider terms:** Yahoo Finance via `yfinance` and RSS is unofficial. For anything beyond the sandbox, use a licensed feed. Alpha Vantage is already wired as a fallback.
4. **Per-agent identities:** all agents share one runtime SA in a single service. A split design is documented.
5. **Sessions:** set `agent_engine_id` (Vertex AI Agent Engine sessions) before scaling past one instance.

## 6. Transition (sanitisation and harvesting)

* Reusable, domain-neutral components to harvest: `tools/resilience.py` (retry, backoff, TTL cache), `tools/evidence.py` + `guardrails/fact_check.py` (evidence-grounded citations and numeric verification), `services/analyst_service.py` (ADK → SSE event bridge with TTFT metrics), `api/auth.py` (IAP JWT), `telemetry.py`, `evals/` (golden dataset + judge harness) and the `terraform/analyst` module.
* Domain-specific pieces to generalise or remove: prompts, strategy engine thresholds, provider adapters, fixtures.
* No secrets are in the repo. `.env` and `*.tfvars` are gitignored.

## 7. Steps to close the pending items

```bash
gcloud auth application-default login
make eval-all                                   # live accuracy, faithfulness and TTFT scorecard
cd terraform/analyst && terraform apply         # see README for the first-apply bootstrap
gcloud builds submit --config cloudbuild.yaml --substitutions=SHORT_SHA=$(git rev-parse --short HEAD) .
```
