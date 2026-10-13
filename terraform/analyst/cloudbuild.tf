# ==============================================================================
# Cloud Build — optional GitHub trigger
# ==============================================================================
# The build SA and its grants are in iam.tf / cloud_run.tf. The trigger below is
# opt-in because it requires the Cloud Build GitHub App to be installed and the
# repository connected in the Cloud Build console first (a one-time, manual,
# OAuth-backed step that Terraform cannot perform).

resource "google_cloudbuild_trigger" "main" {
  count = var.enable_github_trigger ? 1 : 0

  project     = var.project_id
  location    = "global"
  name        = "investment-analyst-main"
  description = "Test, build, push and deploy the Investment Analyst Agent on pushes to main."

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = var.github_branch_regex
    }
  }

  filename        = "cloudbuild.yaml"
  service_account = google_service_account.build.id

  substitutions = {
    _REGION = var.region
  }

  include_build_logs = "INCLUDE_BUILD_LOGS_WITH_STATUS"

  lifecycle {
    precondition {
      condition     = var.github_owner != "" && var.github_repo != ""
      error_message = "github_owner and github_repo must be set when enable_github_trigger = true."
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_project_iam_member.build_log_writer,
  ]
}
