# Day-2 Operations, Incident Response & Disaster Recovery Runbook

This runbook documents standard operating procedures (SOPs), deployment and rollback playbooks, incident triage, and disaster recovery (DR) drills for the **MALIK LLC Investment Analyst Agent**.

---

## 1. Developer Onboarding (< 10 Minutes to Green Build)

### Prerequisites
- Python 3.12+, Node.js 22+, Terraform >= 1.5, Google Cloud SDK (`gcloud`).

### Local Setup & Verification
```bash
# 1. Install backend + frontend dependencies
make install

# 2. Run static analysis (ruff + eslint + tsc) and Terraform validation
make lint
make tf-validate

# 3. Run full unit/integration test suites (647 backend tests @ 99% coverage + 42 frontend tests)
make test

# 4. Run concurrent load & SLA benchmark (25 concurrent turns, p95 < 500ms in-process)
.venv/bin/python -m scripts.load_test --concurrency 25 --p95-sla-ms 500
```

---

## 2. Deployment, Environment Promotion & Canary Rollout

### Environment Parity (`terraform/analyst/environments/`)
All three environments (`dev`, `staging`, `prod`) share the exact same Terraform module (`terraform/analyst/`) parameterized via environment-specific `.tfvars`:

```bash
# Deploy infrastructure to staging or prod
terraform -chdir=terraform/analyst init
terraform -chdir=terraform/analyst plan -var-file="environments/prod.tfvars"
terraform -chdir=terraform/analyst apply -var-file="environments/prod.tfvars"
```

### Progressive Canary Rollout & Instant Rollback (`scripts/deploy_canary.sh`)
Never route 100% of production traffic directly to an untested revision. Use [`scripts/deploy_canary.sh`](../scripts/deploy_canary.sh):

```bash
# Step 1: Deploy new revision at 10% canary traffic and run automated /healthz smoke check
./scripts/deploy_canary.sh \
  --project malik-investment-analyst-prod \
  --region us-central1 \
  --service investment-analyst-backend \
  --image us-central1-docker.pkg.dev/malik-investment-analyst-prod/investment-analyst/investment-analyst-backend:${COMMIT_SHA} \
  --canary-pct 10

# Step 2: After verifying /api/v1/metrics and Cloud Monitoring latency/error dashboards, promote to 100%
./scripts/deploy_canary.sh \
  --project malik-investment-analyst-prod \
  --region us-central1 \
  --service investment-analyst-backend \
  --image us-central1-docker.pkg.dev/malik-investment-analyst-prod/investment-analyst/investment-analyst-backend:${COMMIT_SHA} \
  --canary-pct 10 \
  --promote

# Emergency 1-Command Rollback to Previous Stable Revision (< 15 seconds)
./scripts/deploy_canary.sh \
  --project malik-investment-analyst-prod \
  --region us-central1 \
  --service investment-analyst-backend \
  --rollback
```

---

## 3. Incident Response Playbooks (SEV-1 / SEV-2 / SEV-3)

| Severity | Trigger Condition | Alert Policy (`monitoring.tf`) | Triage & Remediation Steps |
| :---: | :--- | :--- | :--- |
| **SEV-1** | Backend 5xx error rate `> 2%` over 5 min OR Cloud Run service unreachable. | `google_monitoring_alert_policy.backend_error_rate` | 1. Execute immediate canary rollback: `./scripts/deploy_canary.sh --rollback`.<br>2. Query structured error logs in Cloud Logging: `resource.type="cloud_run_revision" severity>=ERROR`.<br>3. Check Vertex AI Gemini quota status in `us-central1` / `global`. |
| **SEV-2** | p95 turn latency `> 30s` over 5 min OR external market provider outage. | `google_monitoring_alert_policy.backend_latency_sla` | 1. Inspect `GET /api/v1/metrics` -> `circuit_breakers` to see which upstream provider (`yahoo`, `alpha_vantage`, `sec_edgar`) tripped `OPEN`.<br>2. If Yahoo Finance is degraded, verify Alpha Vantage fallback key is active in Secret Manager.<br>3. If all external providers are unreachable during a drill, temporarily set `ANALYST_OFFLINE_MODE=true` for cached Continuity-of-Operations mode. |
| **SEV-3** | Spike in `guardrail_blocks` log metric (`> 10 blocks / 5 min`) or fact-check accuracy drop. | `google_logging_metric.guardrail_blocks` | 1. Query BigQuery `audit_log` for `status = 'blocked'` to identify whether a single user is probing prompt injections or a benign financial phrasing triggered a false positive.<br>2. Inspect `fact_check.unverified_numbers` in Firestore `analyst_reports`. |

---

## 4. Disaster Recovery (DR), Backup & Restore Procedures

### Recovery Objectives
- **Recovery Time Objective (RTO)**: **< 15 minutes** (full service restoration in secondary region `us-east1` via Terraform + Artifact Registry).
- **Recovery Point Objective (RPO)**: **< 1 hour** for Firestore `analyst_reports` (Point-in-Time Recovery / Managed Export) and **0 minutes** for BigQuery multi-region/time-travel (`FOR SYSTEM_TIME AS OF`).

### Firestore Managed Export & Application-Level Snapshot Restore
1. **Infrastructure-Level PITR / Export**:
   ```bash
   gcloud firestore export gs://malik-investment-analyst-prod-dr-backups/$(date -u +%Y%m%dT%H%M%SZ) \
     --project=malik-investment-analyst-prod \
     --collection-ids=analyst_reports
   ```
2. **Application-Level Snapshot Export & Restore** ([`analyst/services/report_store.py`](../investment-analyst/analyst/services/report_store.py)):
   - Both `InMemoryReportStore` and `FirestoreReportStore` implement `export_snapshot()` and `restore_snapshot(reports)` (verified in `tests/test_rubric_enhancements.py::TestDisasterRecoverySnapshots`).
3. **BigQuery Time-Travel Recovery**:
   ```sql
   SELECT *
   FROM `malik-investment-analyst-prod.analyst_telemetry.audit_log`
   FOR SYSTEM_TIME AS OF TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR);
   ```

---

## 5. Zero-Downtime Secret Rotation (`alpha-vantage-api-key`)

1. Add the new API key version to Google Secret Manager:
   ```bash
   printf "%s" "${NEW_ALPHA_VANTAGE_KEY}" | gcloud secrets versions add alpha-vantage-api-key \
     --project=malik-investment-analyst-prod \
     --data-file=-
   ```
2. Trigger a rolling Cloud Run revision update (since the container mounts `version = "latest"` in `cloud_run.tf`):
   ```bash
   gcloud run services update investment-analyst-backend \
     --project=malik-investment-analyst-prod \
     --region=us-central1 \
     --update-env-vars="SECRET_ROTATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
   ```
3. Disable the old secret version once `/api/v1/metrics` confirms healthy requests.
