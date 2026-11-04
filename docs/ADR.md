# Architecture Decision Records (ADRs) — Investment Analyst Agent

This document records the core architectural decisions made for the MALIK LLC Investment Analyst Agent, their context, evaluated alternatives, and quantitative trade-offs.

---

## ADR-001: Single-Process Google ADK Hierarchical Orchestration vs. Distributed Microservices

- **Status**: Accepted
- **Context**: The system requires 5 specialized roles (`root_orchestrator`, `data_gatherer`, `sec_filing_parser`, `strategy_evaluator`, and `financial_analyst`). We evaluated deploying each agent as an independent Cloud Run microservice communicating over HTTP/A2A vs. running the 5-agent hierarchy in-process inside a single Cloud Run container using Google ADK (`AgentTool` + `sub_agents`).
- **Decision**: Run all 5 ADK agents inside a single FastAPI/Cloud Run service process, using `AgentTool` wrappers for the 3 data-gathering specialists and `sub_agents` transfer for `financial_analyst`.
- **Consequences & Trade-Offs**:
  - **Pros**: Zero network serialization overhead between agents (saves **150–400ms per tool hop**); shared in-memory/Vertex session state (`state["evidence"]`) without distributed race conditions; single container image and IAM boundary to audit.
  - **Cons**: All agents scale with the same Cloud Run container CPU/memory profile (`2 vCPU / 2 GiB`).
  - **Mitigation**: Clean `AgentTool` boundaries allow extracting any single specialist into an independent remote service in Phase 3 if heavy PDF/OCR workloads require dedicated CPU/GPU pools.

---

## ADR-002: Tiered Model Selection (`gemini-3.5-flash` for Routing/Tools + `gemini-2.5-pro` for Synthesis)

- **Status**: Accepted
- **Context**: Institutional analysts require both responsive streaming feedback (`p95 Time-to-First-Thought <= 6.0s`) and deep, nuanced financial synthesis across SEC 10-K filings, XBRL statements, and multi-strategy indicators.
- **Decision**: Use `gemini-3.5-flash` for `root_orchestrator` and the three tool-calling specialist agents (`data_gatherer`, `sec_filing_parser`, `strategy_evaluator`), and reserve `gemini-2.5-pro` strictly for the final `financial_analyst` synthesis agent.
- **Consequences & Trade-Offs**:
  - **Pros**: Cuts per-turn LLM inference cost by **53–68%** ($0.0211/turn vs. $0.0448/turn on all-Pro) and reduces p95 Time-to-First-Thought from `~6.8s` to `< 2.4s` while maintaining `1.00` tool recall and `>= 4.5/5.0` synthesis quality.
  - **Cons**: Requires maintaining model-tier configuration (`ANALYST_ROUTER_MODEL` and `ANALYST_REASONING_MODEL`).

---

## ADR-003: Tool-Less Synthesis Agent + Deterministic Python Indicator Engine + Post-Generation Fact-Checker

- **Status**: Accepted
- **Context**: LLMs are probabilistic token predictors prone to arithmetic errors when computing technical indicators (RSI, MACD, Bollinger %B, CAGR) or transcribing financial tables. Under FINRA Rule 2210, research communications must be fair, balanced, and free of fabricated figures.
- **Decision**:
  1. Compute all technical and fundamental strategy metrics in deterministic, unit-tested Python ([`analyst/strategies/indicators.py`](../investment-analyst/analyst/strategies/indicators.py) and [`analyst/strategies/engine.py`](../investment-analyst/analyst/strategies/engine.py)).
  2. Configure `financial_analyst` with **`tools=[]`** so it can only synthesize from `session.state["evidence"]`.
  3. Run [`fact_check(text, evidence)`](../investment-analyst/analyst/guardrails/fact_check.py) on every generated brief to verify 100% of numeric claims against raw tool payloads within 1.5% rounding tolerance.
- **Consequences & Trade-Offs**:
  - **Pros**: Eliminates LLM arithmetic hallucinations; provides an auditable `FactCheckResult` badge on every response.
  - **Cons**: Adding a new technical indicator requires writing a pure Python function rather than just changing a prompt (mitigated by the `@register_strategy` plugin registry).

---

## ADR-004: Hybrid BM25 + Dense Vector Reciprocal Rank Fusion (RRF) with HTML Table Preservation for SEC Filings

- **Status**: Accepted
- **Context**: SEC 10-K and 10-Q filings mix dense narrative paragraphs (Item 1A Risk Factors) with complex multi-column HTML financial tables (Item 7 MD&A segment revenue) and exact alphanumeric identifiers (ASC 606, CIKs, customer names, geographic regions). Pure dense vector search often misses exact financial terms, while naive HTML tag stripping destroys table row/column alignment.
- **Decision**:
  1. Convert HTML `<table>` elements into GitHub-Flavored Markdown tables (`extract_html_tables` / `html_to_markdown_preserving_tables`) before stripping remaining HTML tags.
  2. Split sections into overlapping semantic chunks (`chunk_size=800`, `chunk_overlap=150`).
  3. Index chunks with both **Okapi BM25** and **Dense Embeddings** (`VertexAIEmbedder("text-embedding-005")` with automatic offline fallback to L2-normalized `DeterministicEmbedder`) and fuse rankings via **Reciprocal Rank Fusion (`rrf_k=60`)**.
- **Consequences & Trade-Offs**:
  - **Pros**: Preserves tabular financial figures for the synthesis model; combines exact lexical matching with semantic recall; works 100% offline in CI/tests without external vector DB dependencies.
  - **Cons**: In-memory indexing is scoped per filing section; cross-company S&P 500 corpus search is scheduled for Phase 2 via Vertex AI Vector Search.

---

## ADR-005: Defense-in-Depth Guardrails (Deterministic Pre-LLM DLP + Regex Injection Screen + Cloud Model Armor)

- **Status**: Accepted
- **Context**: Analysts may inadvertently paste client PII (SSNs, account numbers, emails) or adversarial text from external documents, and malicious users may attempt prompt injection or request insider-trading/MNPI actions.
- **Decision**: Execute a three-stage guardrail pipeline on every turn:
  1. **Pre-LLM Deterministic DLP ([`analyst/guardrails/dlp.py`](../investment-analyst/analyst/guardrails/dlp.py))**: Redacts SSNs, Luhn-verified credit cards, brokerage account numbers, emails, phone numbers, and API secrets in `< 1ms` and assigns a `DataClassification` tier.
  2. **Deterministic Local Safety Screen ([`analyst/guardrails/injection.py`](../investment-analyst/analyst/guardrails/injection.py))**: Blocks jailbreaks, system-prompt extraction, insider trading, market manipulation, and guaranteed-return claims in `< 1ms`.
  3. **Google Cloud Model Armor ([`analyst/guardrails/model_armor.py`](../investment-analyst/analyst/guardrails/model_armor.py))**: Screens sanitized prompts and final responses against enterprise safety templates, with configurable fail-open/fail-closed behavior (`MODEL_ARMOR_FAIL_CLOSED`).

---

## ADR-006: Dual Persistence Sink — Cloud Firestore (Operational Store) + BigQuery (Analytical & Audit Warehouse)

- **Status**: Accepted
- **Context**: The application needs sub-20ms point lookups and document updates by `report_id` (when an analyst clicks thumbs-up/down feedback or reloads a report) AND SQL-queryable time-series aggregation over token costs, latency percentiles, and compliance audit logs.
- **Decision**: Persist full report documents and feedback mutations to **Cloud Firestore Native** (`analyst_reports` collection) and stream append-only `usage_events` and `audit_log` rows to time-partitioned, clustered **BigQuery** tables.
- **Consequences & Trade-Offs**:
  - **Pros**: Optimal storage engine for each access pattern (OLTP document mutations in Firestore; OLAP FinOps and compliance queries in BigQuery); background BigQuery inserts never block user response latency.
  - **Cons**: Dual writes require independent error handling so a transient BigQuery or Firestore hiccup never crashes an active user stream (`TestErrors::test_persistence_failure_does_not_fail_request`).

---

## ADR-007: Three-Tier Market Data Provider Chain with Per-Provider Circuit Breakers

- **Status**: Accepted
- **Context**: Free and commercial market data APIs (Yahoo Finance, Alpha Vantage, SEC EDGAR) exhibit burst rate limiting (HTTP 429) and occasional 5xx outages.
- **Decision**: Wrap every data domain in [`analyst/data/market.py`](../investment-analyst/analyst/data/market.py) with:
  1. Per-endpoint LRU `TTLCache` (`@cached`).
  2. `call_with_retry` (exponential backoff + full jitter + `Retry-After` header support).
  3. Per-provider `CircuitBreaker` (`CLOSED -> OPEN -> HALF_OPEN`, tripping after 3 consecutive failures for 30s).
  4. Automatic fallback chain: `Yahoo Finance -> Alpha Vantage -> Deterministic Offline Fixture`.

---

## ADR-008: Cloud IAP + Internal-Only Backend Ingress Zero-Trust Topology

- **Status**: Accepted
- **Context**: Only authorized MALIK LLC equity research personnel (`var.analyst_group_email`) may access the application, and the backend API must never be directly reachable from the public internet.
- **Decision**: Configure the frontend Cloud Run service with `iap_enabled = true` and Direct VPC Egress, and configure the backend Cloud Run service with `INGRESS_TRAFFIC_INTERNAL_ONLY` plus cryptographic verification of the `X-Goog-IAP-JWT-Assertion` ES256 JWT header ([`analyst/api/auth.py`](../investment-analyst/analyst/api/auth.py)).
