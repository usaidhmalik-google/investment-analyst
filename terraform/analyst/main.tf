# ==============================================================================
# Shared locals and project metadata
# ==============================================================================

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  labels = {
    app        = "investment-analyst"
    managed_by = "terraform"
    env        = var.environment
  }

  model_armor_enabled = var.model_armor_template != ""

  registry_host = "${var.region}-docker.pkg.dev"
  registry_path = "${local.registry_host}/${var.project_id}/${var.artifact_registry_repository_id}"

  backend_image  = coalesce(var.backend_image, "${local.registry_path}/investment-analyst-backend:latest")
  frontend_image = coalesce(var.frontend_image, "${local.registry_path}/investment-analyst-frontend:latest")

  # Audience of the JWT that IAP (direct Cloud Run integration) signs for the
  # frontend service. The backend verifies X-Goog-IAP-JWT-Assertion against it.
  iap_audience = "/projects/${data.google_project.this.number}/locations/${var.region}/services/${var.frontend_service_name}"

  bq_usage_table = "${var.project_id}.${var.bigquery_dataset_id}.usage_events"
  bq_audit_table = "${var.project_id}.${var.bigquery_dataset_id}.audit_log"
}
