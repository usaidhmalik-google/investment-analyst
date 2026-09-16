# Project Aegis: Agentic Benchmark Scorecard
**Run ID:** `bench_20260916_174237` | **Evaluated Model:** `gemini-2.5-flash`

## 1. Executive Summary Metrics

- **Baseline Latency (Direct Vertex AI):** `9.6008s` (avg per scenario)
- **Cutover Latency (Project Aegis Gateway):** `8.5764s` (avg per scenario)
- **Proxy Overhead Overhead:** `-1.0244s`
- **Tool Calling Fidelity:** `7/7 (100.0%)` identical tool execution matches
- **Total Token Consumption:** Baseline: `27126` vs Aegis: `28256`
- **BigQuery Telemetry Records Logged:** `10` verified audit events

## 2. Head-to-Head Scenario Comparison

| Benchmark ID | Scenario Name | Category | Direct Latency | Aegis Latency | Overhead | Tools (Dir/Aeg) | Tokens (Dir/Aeg) | Fidelity |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BENCH-01** | Single-Ticker Deep Dive (NVDA) | Sequential Multi-Tool Calling | 12.40s | 9.89s | -2.51s (-20.3%) | 3 / 3 | 2934 / 2652 | ✅ MATCH |
| **BENCH-02** | Comparative Valuation (AAPL vs MSFT) | Parallel Entity Reasoning | 15.39s | 9.72s | -5.67s (-36.9%) | 4 / 4 | 3286 / 2415 | ✅ MATCH |
| **BENCH-03** | Balance Sheet & Risk Audit (TSLA) | Quantitative Metric Extraction | 12.40s | 9.39s | -3.01s (-24.3%) | 3 / 3 | 2675 / 2285 | ✅ MATCH |
| **BENCH-04** | Adversarial Prompt Injection Guardrail | Security & Instruction Adherence | 1.60s | 1.32s | -0.28s (-17.8%) | 0 / 0 | 725 / 738 | ✅ MATCH |
| **BENCH-05** | Long-Context Earnings Call Synthesis (Alphabet Q2 2026) | Long-Context Ingestion & Extraction | 9.60s | 12.80s | +3.20s (+33.3%) | 0 / 0 | 14655 / 15226 | ✅ MATCH |
| **BENCH-06** | Scenario Modeling & Stress-Testing | Logical Reasoning & Math Calculation | 5.91s | 5.78s | -0.13s (-2.2%) | 0 / 0 | 1630 / 1675 | ✅ MATCH |
| **BENCH-07** | Financial Trend Charting & Code Generation | Executable Code Generation | 9.91s | 11.14s | +1.24s (+12.5%) | 0 / 0 | 1221 / 3265 | ✅ MATCH |

## 3. BigQuery Audit Telemetry Verification

All cutover requests were verified in BigQuery table `aegis-testing-508614.aegis_telemetry.routing_logs`:

| Timestamp (UTC) | Session ID | Client Type | Gemini Model | HTTP Status | Upstream Latency |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `2026-09-16 17:42:53` | `bench_20260916_174237_aegis_BENCH-01` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `1765.0 ms` |
| `2026-09-16 17:43:01` | `bench_20260916_174237_aegis_BENCH-01` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `8002.6 ms` |
| `2026-09-16 17:43:19` | `bench_20260916_174237_aegis_BENCH-02` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `1450.9 ms` |
| `2026-09-16 17:43:27` | `bench_20260916_174237_aegis_BENCH-02` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `8166.8 ms` |
| `2026-09-16 17:43:43` | `bench_20260916_174237_aegis_BENCH-03` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `1571.3 ms` |
| `2026-09-16 17:43:51` | `bench_20260916_174237_aegis_BENCH-03` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `7717.4 ms` |
| `2026-09-16 17:43:56` | `bench_20260916_174237_aegis_BENCH-04` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `1240.3 ms` |
| `2026-09-16 17:44:20` | `bench_20260916_174237_aegis_BENCH-05` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `12719.9 ms` |
| `2026-09-16 17:44:34` | `bench_20260916_174237_aegis_BENCH-06` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `5700.4 ms` |
| `2026-09-16 17:44:57` | `bench_20260916_174237_aegis_BENCH-07` | `google-genai` | `gemini-2.5-flash` | `200 OK` | `11062.7 ms` |
