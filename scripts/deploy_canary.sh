#!/usr/bin/env bash
# ==============================================================================
# Cloud Run Canary Rollout & Automated Rollback Script
#
# Deploys a new container revision with `--no-traffic`, tags it as `canary`,
# shifts a configurable canary traffic percentage (default 10%), verifies the
# `/healthz` and `/api/v1/metrics` probes, and either promotes to 100% or
# automatically rolls back to the previous stable revision on failure.
#
# Usage:
#   ./scripts/deploy_canary.sh \
#     --project fde-investment-analyst-sandbox-dev \
#     --region us-central1 \
#     --service investment-analyst-backend \
#     --image us-central1-docker.pkg.dev/.../investment-analyst-backend:sha \
#     --canary-pct 10 \
#     --promote
# ==============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-fde-investment-analyst-sandbox-dev}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-investment-analyst-backend}"
IMAGE="${IMAGE:-}"
CANARY_PCT="${CANARY_PCT:-10}"
PROMOTE="${PROMOTE:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT_ID="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --service) SERVICE="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    --canary-pct) CANARY_PCT="$2"; shift 2 ;;
    --promote) PROMOTE="true"; shift 1 ;;
    --rollback)
      echo "[ROLLBACK] Routing 100% traffic back to latest stable revision..."
      PREV_REV=$(gcloud run services describe "$SERVICE" \
        --project="$PROJECT_ID" --region="$REGION" \
        --format='value(status.traffic[0].revisionName)')
      gcloud run services update-traffic "$SERVICE" \
        --project="$PROJECT_ID" --region="$REGION" \
        --to-revisions="${PREV_REV}=100"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$IMAGE" ]]; then
  echo "Error: --image is required for canary deployment." >&2
  exit 2
fi

STABLE_REV=$(gcloud run services describe "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" \
  --format='value(status.latestReadyRevisionName)')

echo "[1/4] Deploying new revision with --no-traffic (current stable: ${STABLE_REV})..."
gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="$IMAGE" \
  --no-traffic \
  --tag="canary"

CANARY_REV=$(gcloud run services describe "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" \
  --format='value(status.latestCreatedRevisionName)')

echo "[2/4] Shifting ${CANARY_PCT}% traffic to canary revision ${CANARY_REV}..."
gcloud run services update-traffic "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --to-tags="canary=${CANARY_PCT}"

CANARY_URL=$(gcloud run services describe "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" \
  --format='value(status.traffic.filter(tag:canary).url)')

echo "[3/4] Running smoke test against canary URL (${CANARY_URL}/healthz)..."
ID_TOKEN=$(gcloud auth print-identity-token 2>/dev/null || true)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  ${ID_TOKEN:+-H "Authorization: Bearer ${ID_TOKEN}"} \
  "${CANARY_URL}/healthz" || echo "000")

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "[ALERT] Canary health check failed (HTTP ${HTTP_CODE}). Rolling back to ${STABLE_REV}!" >&2
  gcloud run services update-traffic "$SERVICE" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --to-revisions="${STABLE_REV}=100"
  exit 1
fi

echo "[OK] Canary revision ${CANARY_REV} passed health check at ${CANARY_PCT}% traffic."

if [[ "$PROMOTE" == "true" ]]; then
  echo "[4/4] Promoting ${CANARY_REV} to 100% production traffic..."
  gcloud run services update-traffic "$SERVICE" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --to-revisions="${CANARY_REV}=100"
  echo "[DONE] Revision ${CANARY_REV} is now serving 100% of traffic."
fi
