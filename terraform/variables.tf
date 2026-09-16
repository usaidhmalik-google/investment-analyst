variable "project_id" {
  description = "The GCP Project ID where Project Aegis will be deployed."
  type        = string
}

variable "existing_vpc_name" {
  description = "The name of the existing brownfield corporate VPC network."
  type        = string
}

variable "existing_subnet_name" {
  description = "The name of the existing brownfield private workload subnet."
  type        = string
}

variable "region" {
  description = "The GCP region for Aegis services and existing subnet."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Name of the Cloud Run v2 service for Project Aegis."
  type        = string
  default     = "aegis-gateway"
}

variable "container_image" {
  description = "Container image URI for Project Aegis runtime service."
  type        = string
  default     = "us-central1-docker.pkg.dev/aegis-testing-508614/aegis-repo/aegis-gateway:v2"
}

variable "dataset_id" {
  description = "BigQuery dataset ID for Aegis routing logs and cost analytics."
  type        = string
  default     = "aegis_telemetry"
}
