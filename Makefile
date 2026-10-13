# Investment Analyst Agent — developer workflow.
# Usage: make <target>. Python deps live in ./.venv, Node in ./.tools/node (see README).

SHELL := /bin/bash
ROOT := $(abspath .)
VENV ?= $(ROOT)/.venv
PY := $(VENV)/bin/python
BACKEND := $(ROOT)/investment-analyst
FRONTEND := $(ROOT)/frontend
NODE_BIN ?= $(ROOT)/.tools/node/bin
TF ?= $(shell command -v terraform 2>/dev/null || echo $(ROOT)/.tools/terraform/terraform)
export PATH := $(NODE_BIN):$(PATH)

.PHONY: help install install-backend install-frontend format lint test test-backend test-frontend \
        eval-all eval-quick run-backend run-backend-offline run-frontend adk-web docker-build tf-validate ci

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install all dependencies

install-backend: ## Create .venv and install backend + dev dependencies
	test -x $(PY) || python3 -m venv $(VENV)
	$(PY) -m pip install -q -r $(BACKEND)/requirements-dev.txt

install-frontend: ## npm ci for the React frontend
	cd $(FRONTEND) && npm ci

format: ## Auto-format backend code
	cd $(BACKEND) && $(VENV)/bin/ruff format . && $(VENV)/bin/ruff check --fix .

lint: ## Lint backend (ruff) and frontend (eslint + tsc)
	cd $(BACKEND) && $(VENV)/bin/ruff format --check . && $(VENV)/bin/ruff check .
	cd $(FRONTEND) && npm run lint && npm run typecheck

test: test-backend test-frontend ## Run all unit tests

test-backend: ## pytest with mocked LLM + APIs, >= 80% coverage gate
	cd $(BACKEND) && ANALYST_OFFLINE_MODE=true $(PY) -m pytest --cov=analyst --cov-report=term-missing --cov-fail-under=80

test-frontend: ## Vitest
	cd $(FRONTEND) && npm test

eval-all: ## Golden-dataset regression + LLM-as-a-Judge (needs Vertex AI ADC)
	cd $(BACKEND) && $(PY) evals/run_evals.py

eval-quick: ## Golden dataset with deterministic checks only (no judge model)
	cd $(BACKEND) && $(PY) evals/run_evals.py --no-judge

run-backend: ## FastAPI on :8080 with live market data (needs Vertex AI ADC)
	cd $(BACKEND) && $(VENV)/bin/uvicorn analyst.main:app --reload --port 8080

run-backend-offline: ## FastAPI on :8080 with deterministic offline fixtures
	cd $(BACKEND) && ANALYST_OFFLINE_MODE=true $(VENV)/bin/uvicorn analyst.main:app --reload --port 8080

run-frontend: ## Vite dev server on :5173 (proxies /api to :8080)
	cd $(FRONTEND) && npm run dev

adk-web: ## ADK developer UI for the agent tree
	cd $(BACKEND) && $(VENV)/bin/adk web adk_agents

docker-build: ## Build backend and frontend images locally
	docker build -t investment-analyst-backend $(BACKEND)
	docker build -t investment-analyst-frontend $(FRONTEND)

tf-validate: ## terraform fmt/validate for terraform/analyst
	cd $(ROOT)/terraform/analyst && $(TF) fmt -check -recursive && $(TF) init -backend=false -input=false >/dev/null && $(TF) validate

ci: lint test tf-validate ## Everything Cloud Build runs before building images
