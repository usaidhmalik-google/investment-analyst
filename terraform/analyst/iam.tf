# ==============================================================================
# Service accounts and least-privilege IAM
# ==============================================================================
#
# Identities:
#   investment-analyst-sa           backend runtime (all ADK agents share it)
#   investment-analyst-frontend-sa  frontend (nginx) runtime
#   investment-analyst-build-sa     Cloud Build CI/CD
#
# Service-level grants (run.invoker, IAP accessor, run.developer) live next to
# the Cloud Run services in cloud_run.tf; resource-scoped data grants live next
# to their resources (secrets.tf, bigquery.tf).

# ------------------------------------------------------------------------------
# Backend runtime SA
# ------------------------------------------------------------------------------

resource "google_service_account" "backend" {
  project      = var.project_id
  account_id   = "investment-analyst-sa"
  display_name = "Investment Analyst backend runtime"
  description  = "Runtime identity for the investment-analyst-backend Cloud Run service. Shared by every ADK agent in the process (orchestrator, data gatherer, financial analyst, fact checker)."

  depends_on = [google_project_service.enabled]
}

locals {
  backend_project_roles = toset(concat(
    [
      "roles/aiplatform.user",         # Gemini via Vertex AI
      "roles/datastore.user",          # Firestore read/write
      "roles/logging.logWriter",       # Structured logs
      "roles/cloudtrace.agent",        # OTEL spans -> Cloud Trace
      "roles/monitoring.metricWriter", # Custom metrics
    ],
    local.model_armor_enabled ? ["roles/modelarmor.user"] : [],
    var.grant_bigquery_job_user ? ["roles/bigquery.jobUser"] : [],
  ))
}

resource "google_project_iam_member" "backend" {
  for_each = local.backend_project_roles

  project = var.project_id
  role    = each.value
  member  = google_service_account.backend.member
}

# ------------------------------------------------------------------------------
# Frontend runtime SA
# ------------------------------------------------------------------------------
# nginx only serves static assets and proxies to the backend. It needs no
# project-level roles; its only grant is roles/run.invoker on the backend
# service (cloud_run.tf).

resource "google_service_account" "frontend" {
  project      = var.project_id
  account_id   = "investment-analyst-frontend-sa"
  display_name = "Investment Analyst frontend runtime"
  description  = "Runtime identity for the investment-analyst-frontend Cloud Run service (nginx reverse proxy)."

  depends_on = [google_project_service.enabled]
}

# ------------------------------------------------------------------------------
# Cloud Build SA
# ------------------------------------------------------------------------------

resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "investment-analyst-build-sa"
  display_name = "Investment Analyst Cloud Build"
  description  = "Runs cloudbuild.yaml: tests, builds/pushes images, deploys new revisions."

  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "build_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = google_service_account.build.member
}

# Push images to this repository only.
resource "google_artifact_registry_repository_iam_member" "build_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.build.member
}

# `gcloud run deploy` must act as the runtime SA of the service it updates.
# Scoped to the two runtime SAs only (not project-wide serviceAccountUser).
resource "google_service_account_iam_member" "build_acts_as_runtime" {
  for_each = {
    backend  = google_service_account.backend.name
    frontend = google_service_account.frontend.name
  }

  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.build.member
}

# ------------------------------------------------------------------------------
# IAP service agent (direct Cloud Run IAP integration)
# ------------------------------------------------------------------------------
# service-<PROJECT_NUMBER>@gcp-sa-iap.iam.gserviceaccount.com — created on
# demand so we can grant it roles/run.invoker on the frontend.

resource "google_project_service_identity" "iap" {
  provider = google-beta

  project = var.project_id
  service = "iap.googleapis.com"

  depends_on = [google_project_service.enabled]
}
