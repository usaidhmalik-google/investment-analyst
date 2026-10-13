# investment-analyst

Enterprise Autonomous Investment Analyst AI Agent powered by Google Cloud Vertex AI and Project Aegis Gateway.

## Overview

`investment-analyst` is a production-grade financial reasoning agent and evaluation platform designed to perform autonomous equity research, financial statement analysis, comparative valuation, earnings call synthesis, and stress-test modeling.

The agent routes all model inference through **Project Aegis AI Gateway** (`aegis-gateway`), a zero-trust, private Cloud Run service that provides:
- **Dynamic Multi-Region & Global Routing:** Automatic routing between regional endpoints (`us-central1-aiplatform.googleapis.com`) and global Model Garden endpoints (`aiplatform.googleapis.com`) for next-gen models (Gemini 3.x).
- **Asynchronous Telemetry & Audit Logging:** Non-blocking streaming of model calls, token usage, latency, and tool invocations into BigQuery (`aegis_telemetry.routing_logs`).
- **Zero-Egress Security Perimeter:** Enforced Cloud Run internal ingress with Direct VPC Egress, eliminating exposure to public networks.

---

## Repository Structure

```text
├── aegis-service/               # Project Aegis Gateway proxy service (FastAPI / Cloud Run)
│   ├── main.py                  # Dynamic proxy router, Vertex AI client, BigQuery audit sink
│   ├── requirements.txt         # FastAPI, httpx, google-cloud-bigquery dependencies
│   └── Dockerfile               # Container definition for Cloud Run deployment
├── investment-analyst/          # Autonomous Investment Analyst Agent
│   ├── agent.py                 # Core agentic loop with function calling and thinking control
│   ├── tools.py                 # Financial data tools (quotes, metrics, news)
│   ├── main.py                  # Entrypoint and interactive CLI
│   └── requirements.txt         # google-genai, google-cloud-aiplatform dependencies
├── terraform/                   # Enterprise Cloud Foundation & Infrastructure-as-Code
│   ├── cloud_run.tf             # Cloud Run v2 service with Direct VPC Egress & Internal Ingress
│   ├── bigquery.tf              # Telemetry audit dataset and partitioned routing table
│   ├── iam.tf                   # Least-privilege service account bindings
│   └── variables.tf             # Project and regional configuration
├── tests/                       # Comprehensive evaluation & benchmark harness
│   ├── run_gemini3_benchmarks.py# Multi-model evaluation harness with LLM-as-a-Judge
│   ├── customer_agent_baseline.py# 7-scenario golden baseline test suite
│   ├── benchmark_analyst.py     # Gateway vs. Direct latency profiling harness
│   ├── prompts/                 # Standardized prompt library & 15k-token earnings transcripts
│   └── outputs/                 # Dedicated benchmark scorecards and telemetry JSONs
├── TESTING_METHODOLOGY_AND_EVALUATION_PROCESS.md # 5-phase testing methodology & agents-cli spec
├── CAPSTONE_COMPLETION_REPORT.md# Executive project completion and infrastructure audit report
└── .gitignore                   # Enterprise filtering for Python, Terraform, and secrets
```

---

## Automated Evaluation & LLM-as-a-Judge

The repository includes a standardized 7-scenario financial benchmark evaluated using `agents-cli` and **Gemini 3.1 Pro** (`gemini-3.1-pro-preview` in `location='global'`) across five core dimensions:
1. **Financial & Mathematical Accuracy**
2. **Completeness & Structure**
3. **Factual Grounding (Zero Hallucination)**
4. **Code Quality & Executability**
5. **Guardrail & Adversarial Prompt Injection Defense**

Dedicated scorecards for all evaluated models (Gemini 3.8 Flash, 3.7 Flash, 3.6 Flash, 3.5 Flash, 3.1 Flash Lite, 3.1 Pro, 2.5 Pro, 2.5 Flash) are available in `tests/outputs/`.
