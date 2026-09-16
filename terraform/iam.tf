# ==============================================================================
# Dedicated Runtime Service Account & Least-Privilege IAM Roles
# ==============================================================================

resource "google_service_account" "aegis_gateway" {
  account_id   = "aegis-gateway-sa"
  display_name = "Aegis Gateway Runtime Service Account"
  description  = "Dedicated runtime service account for Project Aegis Cloud Run service"
  project      = var.project_id
}

locals {
  aegis_roles = [
    "roles/aiplatform.user",     # Direct Vertex AI Gemini model invocation
    "roles/bigquery.dataEditor", # Logging telemetry and cost analytics records
    "roles/logging.logWriter",   # Cloud Logging audit records
  ]
}

resource "google_project_iam_member" "aegis_roles" {
  for_each = toset(local.aegis_roles)

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.aegis_gateway.email}"
}
