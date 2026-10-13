# Investment Analyst Agent — Service Contract (V1)

Shared contract between the FastAPI backend (`investment-analyst/`), the React
frontend (`frontend/`), and the infrastructure (`terraform/analyst/`,
`cloudbuild.yaml`). Any change here must be reflected in all three.

## HTTP API (FastAPI backend, listens on `$PORT`, default `8080`)

| Method | Path               | Body                         | Response                    |
| ------ | ------------------ | ---------------------------- | --------------------------- |
| GET    | `/healthz`         | –                            | `{"status": "ok"}`          |
| GET    | `/api/config`      | –                            | `ConfigResponse`            |
| POST   | `/api/chat`        | `ChatRequest`                | `ChatResponse`              |
| POST   | `/api/chat/stream` | `ChatRequest`                | `text/event-stream` (below) |
| POST   | `/api/feedback`    | `FeedbackRequest`            | `{"status": "ok"}`          |

### ChatRequest

```json
{
  "message": "Give me a brief on NVIDIA's performance this week",
  "session_id": "optional-string (omit to start a new conversation)",
  "strategy": "momentum | value | swing | income | null"
}
```

### ChatResponse

```json
{
  "report_id": "uuid4",
  "session_id": "string",
  "response": "Markdown brief. Every figure carries an inline citation like [Q:NVDA] or [N:NVDA:2].",
  "citations": [
    {
      "id": "Q:NVDA",
      "type": "quote | history | metrics | news | sec_filing | sec_financials | strategy",
      "title": "NVIDIA Corporation real-time quote",
      "source": "Yahoo Finance | Alpha Vantage | SEC EDGAR | Strategy Engine | Offline Fixture",
      "url": "https://... or null",
      "as_of": "ISO-8601 timestamp or date"
    }
  ],
  "fact_check": {
    "verified": true,
    "checked_numbers": 14,
    "matched_numbers": 14,
    "unverified_numbers": [],
    "accuracy": 1.0
  },
  "tools_called": [
    {"agent": "data_gatherer", "tool": "get_stock_quote", "args": {"ticker": "NVDA"}}
  ],
  "latency": {
    "time_to_first_thought_ms": 850,
    "time_to_first_token_ms": 3100,
    "total_ms": 7900
  },
  "usage": {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0},
  "blocked": false,
  "block_reason": null
}
```

### Citation id grammar

`<PREFIX>:<TICKER>[:<qualifier>...]` rendered inline in square brackets.

| Prefix  | Meaning                               | Example                                  |
| ------- | ------------------------------------- | ---------------------------------------- |
| `Q`     | Real-time quote                       | `[Q:NVDA]`                               |
| `H`     | Price history / performance window    | `[H:NVDA:5d]`                            |
| `M`     | Fundamentals / financial metrics      | `[M:NVDA]`                               |
| `N`     | News article (1-based index)          | `[N:NVDA:2]`                             |
| `SEC`   | SEC filing section                    | `[SEC:NVDA:10-K:0001045810-26-000023]`   |
| `XBRL`  | SEC XBRL reported financials          | `[XBRL:NVDA]`                            |
| `S`     | Deterministic strategy evaluation     | `[S:NVDA:momentum]`                      |

Regex used by both frontend and backend: `\[((?:Q|H|M|N|SEC|XBRL|S):[A-Za-z0-9.\-:_]+)\]`

### Streaming (`POST /api/chat/stream`)

Server-Sent Events over a `fetch` response (`event: <type>\ndata: <json>\n\n`):

| Event     | Data                                                                                                   |
| --------- | ------------------------------------------------------------------------------------------------------ |
| `session` | `{"session_id": "..."}` — always first                                                                 |
| `thought` | `{"agent": "data_gatherer", "kind": "tool_call|tool_result|agent_transfer|status", "name": "get_stock_quote", "detail": "NVDA", "elapsed_ms": 812}` |
| `token`   | `{"agent": "financial_analyst", "text": "partial markdown chunk"}`                                     |
| `final`   | `ChatResponse`                                                                                         |
| `error`   | `{"code": "string", "message": "string"}`                                                              |

### FeedbackRequest

```json
{"report_id": "uuid4", "rating": "up | down", "comment": "optional string"}
```

### ConfigResponse

```json
{
  "strategies": ["momentum", "value", "swing", "income"],
  "models": {"router": "gemini-3.5-flash", "reasoning": "gemini-2.5-pro"},
  "offline_mode": false,
  "prompt_version": "v1"
}
```

## Authentication

* Production: the frontend Cloud Run service sits behind **IAP**. nginx forwards
  `X-Goog-IAP-JWT-Assertion` and `X-Goog-Authenticated-User-Email` to the
  backend, which verifies the JWT when `REQUIRE_IAP=true`.
* Local dev: `REQUIRE_IAP=false`; user identity defaults to `local-dev`.

## Backend runtime configuration (environment variables)

| Variable                    | Default                    | Purpose                                                 |
| --------------------------- | -------------------------- | ------------------------------------------------------- |
| `PORT`                      | `8080`                     | HTTP port                                               |
| `GOOGLE_CLOUD_PROJECT`      | –                          | GCP project                                             |
| `GOOGLE_CLOUD_LOCATION`     | `us-central1`              | Vertex AI region                                        |
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE`                     | Route Gemini calls through Vertex AI                    |
| `ANALYST_ROUTER_MODEL`      | `gemini-3.5-flash`         | Orchestrator + gatherer agents                          |
| `ANALYST_REASONING_MODEL`   | `gemini-2.5-pro`           | Financial Analyst synthesis                             |
| `ANALYST_JUDGE_MODEL`       | `gemini-3.5-flash`         | LLM-as-a-judge evals                                    |
| `ALPHA_VANTAGE_SECRET`      | –                          | Secret Manager version resource for the Alpha Vantage key |
| `ALPHA_VANTAGE_API_KEY`     | –                          | Local-dev override (never set in Cloud Run)             |
| `SEC_USER_AGENT`            | `MALIK LLC Investment Analyst admin@malik-llc.example` | Required by SEC EDGAR fair-access policy |
| `SESSION_BACKEND`           | `memory`                   | ADK sessions: `memory`, `database` or `vertex`          |
| `SESSION_DB_URL`            | –                          | SQLAlchemy async URL when `SESSION_BACKEND=database`    |
| `AGENT_ENGINE_ID`           | –                          | Vertex AI Agent Engine id when `SESSION_BACKEND=vertex` |
| `AGENT_TIMEOUT_SECONDS`     | `180`                      | Upper bound for one agent turn                          |
| `PERSISTENCE_BACKEND`       | `memory`                   | `memory` or `firestore`                                 |
| `FIRESTORE_DATABASE`        | `(default)`                | Firestore database id                                   |
| `FIRESTORE_COLLECTION`      | `analyst_reports`          | Report + feedback collection                            |
| `BQ_USAGE_TABLE`            | –                          | `project.dataset.table` for token/latency telemetry     |
| `BQ_AUDIT_TABLE`            | –                          | `project.dataset.table` for access audit trail          |
| `ENABLE_CLOUD_TRACE`        | `false`                    | Export OTEL spans to Cloud Trace                        |
| `REQUIRE_IAP`               | `false`                    | Enforce IAP JWT verification                            |
| `IAP_AUDIENCE`              | –                          | Expected IAP JWT audience                               |
| `MODEL_ARMOR_TEMPLATE`      | –                          | `projects/P/locations/L/templates/T` (optional)         |
| `PROMPT_VERSION`            | `v1`                       | Versioned prompt set to load                            |
| `ANALYST_OFFLINE_MODE`      | `false`                    | Use bundled fixtures instead of live market APIs (demo/CI only) |
| `LOG_LEVEL`                 | `INFO`                     | Structured JSON log level                               |

## Frontend runtime configuration

nginx container listens on `$PORT` (default `8080`), serves the Vite build,
and reverse-proxies `/api/` and `/healthz` to `$BACKEND_URL` with
`proxy_buffering off` (required for SSE). With `BACKEND_ID_TOKEN=true` it also
attaches a metadata-server ID token (audience `$BACKEND_URL`) as `Authorization`.

## Session ids

`session_id` is always minted by the server. A request carrying an unknown id, or an
id that belongs to another user, starts a new conversation, and the new id is returned
in the `session` event and in `ChatResponse.session_id`.
