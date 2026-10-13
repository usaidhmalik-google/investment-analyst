# ==============================================================================
# Secret Manager — Alpha Vantage API key
# ==============================================================================
# Terraform manages the secret CONTAINER only. The value is added out-of-band so
# it never lands in Terraform state or source control:
#
#   printf '%s' "$ALPHA_VANTAGE_API_KEY" | gcloud secrets versions add \
#     alpha-vantage-api-key --data-file=- --project=<PROJECT_ID>
#
# The backend receives the version resource name (ALPHA_VANTAGE_SECRET) and
# reads the value at runtime with its own identity.

resource "google_secret_manager_secret" "alpha_vantage" {
  project   = var.project_id
  secret_id = var.alpha_vantage_secret_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

# Secret-level (not project-level) accessor grant: the backend can read this one
# secret and nothing else in Secret Manager.
resource "google_secret_manager_secret_iam_member" "backend_alpha_vantage_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.alpha_vantage.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.backend.member
}
