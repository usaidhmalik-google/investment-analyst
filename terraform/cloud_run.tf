# ==============================================================================
# Cloud Run v2 Service for Project Aegis
# ==============================================================================
# Configured with:
# - Private Ingress: INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER
# - Direct VPC Egress: Attached directly to existing customer workload subnet
# - ALL_TRAFFIC egress routing ensuring all outbound traffic traverses corporate VPC

resource "google_cloud_run_v2_service" "aegis" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  # Private ingress: Accessible only via Internal HTTP(S) Load Balancer or VPC internal clients
  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = google_service_account.aegis_gateway.email

    # Direct VPC Egress configuration (Zero-disruption using existing subnet)
    vpc_access {
      network_interfaces {
        subnetwork = data.google_compute_subnetwork.existing.id
      }
      egress = "ALL_TRAFFIC"
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "BIGQUERY_DATASET"
        value = google_bigquery_dataset.aegis_telemetry.dataset_id
      }

      env {
        name  = "GCP_REGION"
        value = var.region
      }

      env {
        name  = "VPC_NETWORK"
        value = data.google_compute_network.existing.name
      }

      env {
        name  = "VPC_SUBNETWORK"
        value = data.google_compute_subnetwork.existing.name
      }
    }
  }

  depends_on = [
    google_project_iam_member.aegis_roles,
  ]
}

# Allow internal callers within VPC to invoke the Aegis gateway
resource "google_cloud_run_v2_service_iam_member" "internal_invoker" {
  name     = google_cloud_run_v2_service.aegis.name
  location = var.region
  project  = var.project_id
  role     = "roles/run.invoker"
  member   = "serviceAccount:corp-workload-sa@${var.project_id}.iam.gserviceaccount.com"
}
