# First live run on Google Cloud: what you need to know

This is the checklist for the first time the system runs against **real Gemini on Vertex AI** and real GCP services. It works from Antigravity, Cloud Shell or a Cloud Workstation.

> [!IMPORTANT]
> Until now the agents have only been exercised with **scripted fake LLMs**. That's the TDD's "pytest with mocked LLM responses" requirement, and it covers the wiring, tools, fact checker and API. The machine the code was built on had no Vertex AI credentials. **Expect the first live run to need prompt and latency tuning.** Run `make eval-all` and iterate until it passes.

## 0. Prerequisites

```bash
git clone https://github.com/usaidhmalik-google/investment-analyst && cd investment-analyst
git checkout feat/multi-agent-tdd
gcloud auth login
gcloud auth application-default login          # ADC: used by ADK, the eval judge, Firestore, BigQuery
gcloud config set project fde-investment-analyst-sandbox-dev
gcloud services enable aiplatform.googleapis.com   # minimum for a local live run
make install-backend                            # ./.venv with backend + dev deps (Python 3.11+)
cp investment-analyst/.env.example investment-analyst/.env
```

Edit `investment-analyst/.env`:

| Variable | Set to | Why |
| --- | --- | --- |
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` | Without it, ADK looks for a Gemini **API key** and fails |
| `GOOGLE_CLOUD_PROJECT` | your sandbox project | |
| `GOOGLE_CLOUD_LOCATION` | `global` | **Gemini 3.x (e.g. `gemini-3.5-flash`) is only served from the global endpoint.** `us-central1` returns 404 / model not found. The legacy agent already did this. |
| `SEC_USER_AGENT` | `MALIK LLC Investment Analyst <your-email>` | SEC EDGAR blocks generic or placeholder user agents (HTTP 403) |
| `ALPHA_VANTAGE_API_KEY` | free key from alphavantage.co (optional locally) | Fallback when Yahoo rate-limits or blocks you, which is common from cloud IPs |

## 1. Preflight (about 30 s)

```bash
cd investment-analyst && ../.venv/bin/python scripts/preflight.py
```

It checks ADC, the Vertex flag, that **each configured model actually responds** at the configured location, Yahoo quote and RSS, SEC with your user agent, Alpha Vantage, and Agent Engine sessions if enabled. Fix every FAIL before going on.

**If a model name fails:** the defaults follow the tiered Gemini 3.x benchmark (`ANALYST_ROUTER_MODEL=gemini-3.5-flash`, `ANALYST_REASONING_MODEL=gemini-3.8-flash`, `ANALYST_JUDGE_MODEL=gemini-3.5-flash`). Swap them through env vars; no code changes are needed. Check Model Garden for the exact ids available to your project, since preview ids sometimes have a `-preview` suffix.

## 2. Live evaluation (the source of your panel numbers)

```bash
make eval-quick     # real Gemini agents over deterministic fixtures; deterministic gates only
make eval-all       # adds the Gemini judge; writes evals/results/SCORECARD_<ts>.md
```

Gates: fact-check accuracy = 100%, tool recall ≥ 0.9, guardrail pass = 100%, TTFT p95 ≤ 6 s, judge faithfulness and mean ≥ 4/5. **Commit the scorecard** under `investment-analyst/evals/results/`. It's evidence for the panel.

What to expect, and where to tune:

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `fact_check.accuracy < 1` | The analyst computed or rounded a number that isn't in the evidence | Tighten `analyst/prompts/v1/financial_analyst.md`, or add the derived value to the tool output (raw number) |
| The orchestrator answers directly without calling specialists | Routing prompt too weak for the router model | Edit `prompts/v1/orchestrator.md`; try another router model |
| The orchestrator never transfers to `financial_analyst` | Same as above | The prompt already says "always transfer"; strengthen it, or check the logged thought events |
| TTFT or total latency too high | Thinking budget, model tier, sequential tool calls | Try a Flash model for the analyst; look at the eval latency columns; the prompts ask for parallel calls |
| Judge scores missing or erroring | Judge model id or location | `ANALYST_JUDGE_MODEL`, `--judge-location global` |
| `RESOURCE_EXHAUSTED` / 429 from Vertex | Quota | Run fewer cases (`--case <id>`), request quota |

Re-benchmark the **reasoning model** before the panel. The legacy benchmark (`tests/outputs/BENCHMARK_SCORECARD_models_and_judge.md`) found 2.5 Flash faster *and* rated higher than 2.5 Pro. Run `make eval-all` with each `ANALYST_REASONING_MODEL` and keep the scorecards as evidence for your model choice.

## 3. Run it locally end to end

```bash
make run-backend           # live market data, :8080   (or run-backend-offline for fixtures)
make run-frontend          # :5173 (needs Node 20: see frontend/README.md)
make adk-web               # ADK dev UI on the same agent tree (shows every agent/tool step)
```

## 4. Deploy (Terraform + Cloud Build)

Follow `terraform/analyst/README.md`. The things that will bite:

1. **The first `terraform apply` fails if the images don't exist yet.** Use the targeted apply or placeholder image described in the README, push images with Cloud Build, then apply fully.
2. **`analyst_group_email`** (the IAP access group) is required. Add yourself to it, or you'll get a 403 at IAP.
3. **The subnet must have Private Google Access** for the frontend to reach the internal backend through Direct VPC egress.
4. **`vertex_ai_location` defaults to `global`** (the Gemini endpoint). `region` (`us-central1`) is for Cloud Run, Firestore, BigQuery and Agent Engine.
5. **IAP audience:** the backend verifies `IAP_AUDIENCE = /projects/<NUMBER>/locations/<region>/services/<frontend>`. If every request returns 401 after login, decode the `x-goog-iap-jwt-assertion` header and compare its `aud` claim with `IAP_AUDIENCE`.
6. **Alpha Vantage secret:** Terraform creates the secret but not its value. Run `printf %s "$KEY" | gcloud secrets versions add alpha-vantage-api-key --data-file=-`. Cloud Run IPs are often throttled by Yahoo, so set this before demoing.
7. **Sessions:** with more than one backend instance, set `agent_engine_id` (Vertex AI Agent Engine). Otherwise follow-up turns can lose context.
8. **`cloudbuild.yaml` `serviceAccount` field:** if Cloud Build rejects the `$PROJECT_ID` substitution there, hardcode the build SA email or pass `--service-account`.
9. **Never built in a container before:** `investment-analyst/Dockerfile` and `frontend/Dockerfile` (nginx templates) haven't run in Docker yet. Watch the first Cloud Build logs. The frontend container exits immediately if `BACKEND_URL` is missing.
10. **Model Armor** is off until `model_armor_template` is set. The local injection screen is always on.

## 5. Post-deploy smoke test

```bash
URL=$(cd terraform/analyst && terraform output -raw frontend_url)
# In a browser (IAP login): ask "Give me a brief on NVIDIA's performance this week and the latest news on their new chips"
# Check: streamed thoughts -> brief with [Q:NVDA]-style chips -> Sources panel -> fact-check badge -> thumbs up works
gcloud logging read 'resource.type="cloud_run_revision" AND jsonPayload.message="usage"' --limit 5 --format json
bq query --use_legacy_sql=false 'SELECT ts, user, tickers, ttft_ms, total_tokens FROM analyst_telemetry.usage_events ORDER BY ts DESC LIMIT 5'
```

Then open Cloud Trace for the request. You should see `analyst.turn` with the ADK agent, tool and LLM spans nested under the FastAPI span.

## 6. Feed results back

- Put real eval numbers, latency and cost in `docs/PRR_READOUT.md`.
- Add anything that broke to the **Lessons learned** table in `AGENTS.md`, in the same commit as the fix.
