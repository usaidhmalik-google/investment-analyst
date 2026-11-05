# System Architecture & Design Artifacts — Investment Analyst Agent

This document provides the complete system design artifacts for the **MALIK LLC Investment Analyst Agent**:
1. **System Context & GCP Infrastructure Architecture Diagram**
2. **Multi-Agent Cognitive Architecture & Sequence Diagram**
3. **Data Flow & Enterprise Data Classification Boundary Diagram**
4. **Resilience, Caching & Circuit-Breaker State Machine**
5. **CI/CD Pipeline & Canary Traffic Rollout Diagram**

---

## 1. GCP System Architecture & Zero-Trust Network Topology

```mermaid
flowchart TB
    subgraph Users["MALIK LLC Research Desk"]
        Analyst["Equity Research Analyst / PM\n(Browser SSE Client)"]
    end

    subgraph Edge["Google Cloud Edge & Zero-Trust Perimeter"]
        WAF["Cloud Armor WAF\n(OWASP XSS/SQLi + 120 RPM Rate Limit)"]
        IAP["Cloud Identity-Aware Proxy (IAP)\n(Google Group IAM + ES256 JWT)"]
    end

    subgraphVPC["VPC Network (Private Google Access)"]
    subgraph CloudRun["Cloud Run Serverless Compute (us-central1)"]
        FE["investment-analyst-frontend\n(React 19 + Nginx Reverse Proxy)\nSA: analyst-frontend"]
        BE["investment-analyst-backend\n(FastAPI + Google ADK Runtime)\nIngress: INTERNAL_ONLY\nSA: analyst-backend"]
    end

    subgraph Guardrails["Defense-in-Depth Guardrail Layer"]
        DLP["Deterministic DLP Scanner\n(SSN / CC Luhn / Email / Phone / Secrets)"]
        RegexScreen["Local Prompt-Injection & FINRA Screen\n(MNPI / Manipulation / Return Guarantees)"]
        Armor["Google Cloud Model Armor\n(Input & Output Template Screening)"]
        FactCheck["Deterministic Numeric Fact-Checker\n(Matched at Displayed Precision: Half a Unit of Last Digit)"]
    end

    subgraph ADK["Google ADK 5-Agent Hierarchy"]
        Orch["root_orchestrator\n(gemini-3.5-flash)"]
        DG["data_gatherer\n(gemini-3.5-flash · 5 Market Tools)"]
        SEC["sec_filing_parser\n(gemini-3.5-flash · 4 EDGAR/XBRL/RAG Tools)"]
        SE["strategy_evaluator\n(gemini-3.5-flash · 4 Strategies + Plugins)"]
        FA["financial_analyst\n(gemini-3.8-flash · ZERO Tools)"]
    end

    subgraph Data["Managed Storage, Secrets & Observability"]
        FS[("Cloud Firestore Native\n(analyst_reports + feedback)")]
        BQ[("BigQuery Partitioned Tables\n(usage_events + audit_log)")]
        SM["Secret Manager\n(alpha-vantage-api-key)"]
        Otel["Cloud Trace + Cloud Logging\n+ Cloud Monitoring Alerts"]
    end

    subgraph External["External Financial Data Providers (TTLCache + Retry + CircuitBreaker)"]
        EDGAR["SEC EDGAR REST & XBRL APIs"]
        YF["Yahoo Finance API"]
        AV["Alpha Vantage API"]
    end

    Analyst -->|HTTPS| WAF --> IAP --> FE
    FE -->|Direct VPC Egress + IAP JWT| BE
    BE --> DLP --> RegexScreen --> Armor --> Orch
    Orch -->|single_turn sub-agent tool| DG
    Orch -->|single_turn sub-agent tool| SEC
    Orch -->|single_turn sub-agent tool| SE
    Orch -->|transfer_to_agent| FA
    FA --> FactCheck
    DG --> YF & AV
    SEC --> EDGAR
    BE --> FS & BQ & SM & Otel
```

---

## 2. Multi-Agent Turn Execution Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User as Equity Analyst (Browser)
    participant FE as Nginx / React Frontend
    participant API as FastAPI (/api/v1/chat/stream)
    participant Guard as DLP + Injection + Model Armor
    participant Orch as root_orchestrator (3.5 Flash)
    participant Spec as Specialist Sub-Agents (3.5 Flash, single_turn)
    participant State as ADK Session State (state["evidence"])
    participant Synth as financial_analyst (3.8 Flash, No Tools)
    participant FC as Numeric Fact-Checker
    participant Store as Firestore + BigQuery + Webhooks

    User->>FE: POST /api/v1/chat/stream {message, strategy}
    FE->>API: Forward request + X-Goog-IAP-JWT-Assertion
    API->>API: Verify IAP ES256 JWT & resolve UserIdentity
    API-->>User: SSE event: session {session_id}

    API->>Guard: 1. dlp.scan_and_redact(message)
    API->>Guard: 2. injection.screen_prompt(sanitized)
    API->>Guard: 3. model_armor.screen_prompt(sanitized)
    alt Prompt Blocked by Guardrail
        Guard-->>API: Verdict(blocked=True, category)
        API->>Store: Persist blocked audit record + emit guardrail.blocked
        API-->>User: SSE event: final {blocked: true, block_reason}
    else Prompt Allowed
        API->>Orch: Runner.run_async(sanitized_message, state_delta={strategy})
        par Parallel Specialist Tool Gathering
            Orch->>Spec: data_gatherer(quote, metrics, history, news, peers)
            Spec->>State: record_evidence([Q:T], [M:T], [H:T:1y], [N:T])
            API-->>User: SSE event: thought {tool_call / tool_result}
        and
            Orch->>Spec: sec_filing_parser(list_filings, get_xbrl, search_sec_filing)
            Spec->>State: record_evidence([SEC:T:10-K:ACC], [XBRL:T])
            API-->>User: SSE event: thought {tool_call / tool_result}
        and
            Orch->>Spec: strategy_evaluator(evaluate_strategy)
            Spec->>State: record_evidence([S:T:strategy])
            API-->>User: SSE event: thought {tool_call / tool_result}
        end
        Orch->>Synth: transfer_to_agent("financial_analyst")
        API-->>User: SSE event: thought {agent_transfer: financial_analyst}
        Synth->>State: Read all recorded evidence & citations
        loop Streaming Synthesis Tokens
            Synth-->>API: Partial token chunk
            API-->>User: SSE event: token {agent: financial_analyst, text}
        end
        API->>Guard: model_armor.screen_response(final_text) + dlp.scan_and_redact
        API->>FC: fact_check(final_text, state["evidence"])
        FC-->>API: FactCheckResult(verified, accuracy, unverified_numbers)
        API->>Store: Save Firestore report + BigQuery usage/audit + emit report.completed
        API-->>User: SSE event: final {report_id, response, citations, fact_check, latency, usage}
    end
```

---

## 3. Data Flow & Enterprise Data Classification Boundaries

All payloads traversing the system are tagged by [`analyst/guardrails/dlp.py`](../investment-analyst/analyst/guardrails/dlp.py) into four enterprise sensitivity tiers:

```mermaid
flowchart LR
    subgraph T1["Tier 1: PUBLIC_MARKET_DATA"]
        M1["SEC EDGAR 10-K / 10-Q / 8-K / XBRL"]
        M2["Yahoo Finance / Alpha Vantage Quotes & Bars"]
    end

    subgraph T4["Tier 4: RESTRICTED_PII_OR_CREDENTIAL"]
        P1["Raw User Prompt with Accidental PII\n(SSN / Credit Card / Email / Phone / Secret)"]
    end

    subgraph RedactionGate["Pre-Ingestion Deterministic DLP Gate"]
        DLPScan["dlp.scan_and_redact()\nReplaces PII with [REDACTED:*] tokens"]
    end

    subgraph T2["Tier 2: INTERNAL_ANALYST_WORK_PRODUCT"]
        Sanitized["Sanitized Prompt + Session Evidence Ledger"]
        Brief["Synthesized Investment Brief + Fact-Check Metadata"]
    end

    subgraph Storage["Encrypted Persistence & Telemetry"]
        FSStore["Firestore: analyst_reports\n(Stores ONLY Sanitized Prompt & Brief)"]
        BQSink["BigQuery: usage_events & audit_log\n(Zero Prompt/PII Content Stored)"]
    end

    P1 --> DLPScan --> Sanitized
    M1 & M2 --> Sanitized
    Sanitized --> Brief
    Brief --> FSStore
    Brief --> BQSink
```

---

## 4. Resilience, Caching & Circuit-Breaker State Machine

Every external data provider (`yahoo`, `alpha_vantage`, `sec_edgar`) is protected by a per-provider [`CircuitBreaker`](../investment-analyst/analyst/tools/resilience.py) and LRU [`TTLCache`](../investment-analyst/analyst/tools/resilience.py):

```mermaid
stateDiagram-v2
    [*] --> CLOSED
    CLOSED --> CLOSED: Call succeeds (failure_count = 0)
    CLOSED --> CLOSED: Transient error < failure_threshold (3)\n(Retried via exponential backoff + jitter)
    CLOSED --> OPEN: Consecutive failures >= 3\n(Trips breaker; fallback provider invoked immediately)
    OPEN --> OPEN: Request arrives before recovery_timeout (30s)\nFast-fails with CircuitBreakerOpenError (< 0.1ms)
    OPEN --> HALF_OPEN: recovery_timeout (30s) elapsed
    HALF_OPEN --> CLOSED: Probe request succeeds\n(Reset failure_count = 0)
    HALF_OPEN --> OPEN: Probe request fails\n(Re-open for another 30s)
```

---

## 5. CI/CD Pipeline & Canary Traffic Rollout

```mermaid
flowchart LR
    Commit["Git Push / PR"] --> Lint["Stage 1: Static Analysis\nruff check + eslint + tsc + terraform validate"]
    Lint --> Unit["Stage 2: Unit & Integration Tests\npytest (647 tests, 99% cov) + vitest (42 tests)"]
    Unit --> Build["Stage 3: Container Build\nMulti-stage non-root Docker images -> Artifact Registry"]
    Build --> Canary["Stage 4: Cloud Run Canary Deploy\nscripts/deploy_canary.sh (--no-traffic, 10% canary tag)"]
    Canary --> Smoke{"Stage 5: Smoke & Eval Gate\n/healthz + /api/v1/metrics + run_evals.py"}
    Smoke -->|PASS| Promote["Promote Revision to 100% Traffic"]
    Smoke -->|FAIL| Rollback["Instant Automated Rollback\n100% Traffic to Previous Stable Revision"]
```
