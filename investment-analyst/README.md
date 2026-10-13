# Investment Analyst — backend

This is the FastAPI and Google ADK service. For the overall architecture and design traceability, see the [root README](../README.md). The HTTP and SSE contract is in [docs/API_CONTRACT.md](../docs/API_CONTRACT.md).

```bash
# from the repo root
make install-backend
make test-backend           # offline: scripted fake LLMs + mocked APIs, coverage gate 80%
make run-backend-offline    # uvicorn on :8080 with deterministic fixtures (agents still call Vertex AI)
make adk-web                # ADK dev UI over the same agent tree
make eval-all               # golden dataset + Gemini judge (needs `gcloud auth application-default login`)
```

## Package map

| Module | Responsibility |
| --- | --- |
| `analyst/agents` | Root Orchestrator, Data Gatherer, SEC Filing Parser, Strategy Evaluator and Financial Analyst (ADK); input guardrail callback |
| `analyst/tools` | ADK tool functions, the evidence/citation registry, `safe_tool`, retry/backoff and TTL cache |
| `analyst/data` | Provider adapters (yfinance, Yahoo RSS, Alpha Vantage, SEC EDGAR), Pydantic schemas, offline fixtures, Secret Manager |
| `analyst/strategies` | Pure indicator math and the deterministic Momentum/Value/Swing/Income engine |
| `analyst/guardrails` | Prompt-injection and trade screen, Model Armor client, numeric fact checker |
| `analyst/prompts/v1` | Versioned prompts (`PROMPT_VERSION`) |
| `analyst/services` | Turn orchestration and SSE events, Firestore report store, BigQuery usage and audit sink |
| `analyst/api` | FastAPI routes, IAP JWT verification, request and response models |
| `analyst/telemetry.py` | OpenTelemetry tracer provider (Cloud Trace) and Cloud Logging JSON formatter |

## Configuration

All settings are environment variables. They're listed in [docs/API_CONTRACT.md](../docs/API_CONTRACT.md#backend-runtime-configuration-environment-variables) and in [.env.example](.env.example).

To add a new prompt version, copy `analyst/prompts/v1` to `analyst/prompts/v2`, edit it, and deploy with `PROMPT_VERSION=v2`. Each report stores the content hash of the prompts that produced it.
