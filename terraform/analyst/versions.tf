# ==============================================================================
# Investment Analyst Agent — Terraform root module
# ==============================================================================
# Independent from the Aegis root module in ../ (separate state, separate
# providers). Run all commands from this directory.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.30"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.30"
    }
  }

  # Remote state is strongly recommended for anything beyond a personal
  # sandbox. Uncomment and point at a pre-created, versioned GCS bucket:
  #
  # backend "gcs" {
  #   bucket = "<STATE_BUCKET>"
  #   prefix = "investment-analyst/dev"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Applied to every resource that supports labels.
  default_labels = local.labels
}

provider "google-beta" {
  project = var.project_id
  region  = var.region

  default_labels = local.labels
}
