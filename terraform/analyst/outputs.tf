# ==============================================================================
# Outputs
# ==============================================================================

output "frontend_url" {
  description = "IAP-protected URL analysts open in the browser."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "backend_url" {
  description = "Internal-only backend URL (reachable from the VPC only). Injected into the frontend as BACKEND_URL."
  value       = google_cloud_run_v2_service.backend.uri
}

output "iap_audience" {
  description = "Expected IAP JWT audience (backend IAP_AUDIENCE)."
  value       = local.iap_audience
}

output "backend_service_account" {
  description = "Backend runtime service account (shared by all ADK agents)."
  value       = google_service_account.backend.email
}

output "frontend_service_account" {
  description = "Frontend runtime service account."
  value       = google_service_account.frontend.email
}

output "build_service_account" {
  description = "Cloud Build service account (use with `gcloud builds submit --service-account`)."
  value       = google_service_account.build.id
}

output "artifact_registry_repository" {
  description = "Docker repository path for images."
  value       = local.registry_path
}

output "backend_image_default" {
  description = "Image reference used when the backend service was created."
  value       = local.backend_image
}

output "frontend_image_default" {
  description = "Image reference used when the frontend service was created."
  value       = local.frontend_image
}

output "alpha_vantage_secret" {
  description = "Secret Manager secret resource name (add a version with gcloud)."
  value       = google_secret_manager_secret.alpha_vantage.id
}

output "bq_usage_table" {
  description = "Fully qualified usage telemetry table (BQ_USAGE_TABLE)."
  value       = local.bq_usage_table
}

output "bq_audit_table" {
  description = "Fully qualified audit log table (BQ_AUDIT_TABLE)."
  value       = local.bq_audit_table
}

output "cloudbuild_trigger_id" {
  description = "Cloud Build trigger id (null when enable_github_trigger = false)."
  value       = one(google_cloudbuild_trigger.main[*].trigger_id)
}
