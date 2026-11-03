# ==============================================================================
# Required Google APIs
# ==============================================================================

locals {
  base_services = [
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudtrace.googleapis.com",
    "compute.googleapis.com", # Direct VPC egress
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iap.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ]

  services = var.enable_apis ? toset(concat(
    local.base_services,
    local.model_armor_enabled ? ["modelarmor.googleapis.com"] : [],
  )) : toset([])
}

resource "google_project_service" "enabled" {
  for_each = local.services

  project = var.project_id
  service = each.value

  # Never disable APIs on destroy: other workloads in the project may rely on them.
  disable_on_destroy         = false
  disable_dependent_services = false
}
