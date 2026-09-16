# ==============================================================================
# BigQuery Telemetry Dataset for Routing Logs & Cost Analytics
# ==============================================================================

resource "google_bigquery_dataset" "aegis_telemetry" {
  dataset_id                  = var.dataset_id
  friendly_name               = "Aegis Telemetry Dataset"
  description                 = "Dedicated BigQuery dataset for Aegis routing logs, audit telemetry, and token/cost analytics"
  location                    = var.region
  project                     = var.project_id
  delete_contents_on_destroy  = false

  labels = {
    environment = "enterprise-brownfield"
    service     = "aegis-gateway"
    managed_by  = "terraform"
  }
}
