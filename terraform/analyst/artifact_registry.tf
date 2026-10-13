# ==============================================================================
# Artifact Registry — container images for backend and frontend
# ==============================================================================

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repository_id
  description   = "Investment Analyst Agent container images (backend + frontend)."
  format        = "DOCKER"

  # Keep the 20 most recent versions of each image; clean up untagged layers
  # older than 14 days.
  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 20
    }
  }

  cleanup_policies {
    id     = "delete-old-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "1209600s"
    }
  }

  depends_on = [google_project_service.enabled]
}
