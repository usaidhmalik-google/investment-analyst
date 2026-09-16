# ==============================================================================
# Brownfield Existing Infrastructure Data Sources (Zero-Disruption)
# ==============================================================================
# These data sources look up existing networking infrastructure without creating,
# modifying, or destroying existing VPC networks or subnetworks.

data "google_compute_network" "existing" {
  name    = var.existing_vpc_name
  project = var.project_id
}

data "google_compute_subnetwork" "existing" {
  name    = var.existing_subnet_name
  region  = var.region
  project = var.project_id
}
