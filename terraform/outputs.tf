# ==============================================================================
# Terraform Outputs
# ==============================================================================

output "cloud_run_service_name" {
  description = "The name of the deployed Aegis Cloud Run service."
  value       = google_cloud_run_v2_service.aegis.name
}

output "cloud_run_service_uri" {
  description = "The internal URI of the deployed Aegis Cloud Run service."
  value       = google_cloud_run_v2_service.aegis.uri
}

output "cloud_run_ingress" {
  description = "The ingress configuration mode of the Aegis Cloud Run service."
  value       = google_cloud_run_v2_service.aegis.ingress
}

output "aegis_service_account" {
  description = "Email of the dedicated runtime Service Account for Aegis."
  value       = google_service_account.aegis_gateway.email
}

output "bigquery_dataset_id" {
  description = "ID of the BigQuery telemetry dataset."
  value       = google_bigquery_dataset.aegis_telemetry.dataset_id
}

output "existing_vpc_name" {
  description = "Name of the existing corporate VPC referenced via data source."
  value       = data.google_compute_network.existing.name
}

output "existing_subnet_name" {
  description = "Name of the existing workload subnet referenced via data source."
  value       = data.google_compute_subnetwork.existing.name
}

output "existing_subnet_cidr" {
  description = "CIDR range of the existing workload subnet."
  value       = data.google_compute_subnetwork.existing.ip_cidr_range
}

output "vpc_access_subnetwork" {
  description = "Direct VPC egress subnetwork ID configured on Cloud Run."
  value       = data.google_compute_subnetwork.existing.id
}
