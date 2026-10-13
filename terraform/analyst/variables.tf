# ==============================================================================
# Input variables
# ==============================================================================

# ------------------------------------------------------------------------------
# Project / environment
# ------------------------------------------------------------------------------

variable "project_id" {
  description = "GCP project that hosts the Investment Analyst Agent."
  type        = string
  default     = "fde-investment-analyst-sandbox-dev"
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry, Vertex AI and Cloud Build."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment name, used for the `env` label."
  type        = string
  default     = "dev"
}

variable "deletion_protection" {
  description = "Enable deletion protection on Cloud Run services and BigQuery tables. Set to true outside of throwaway dev sandboxes."
  type        = bool
  default     = false
}

variable "enable_apis" {
  description = "Enable the required Google APIs via google_project_service. Set to false if APIs are managed centrally (e.g. by a project factory)."
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------------
# Access control
# ------------------------------------------------------------------------------

variable "analyst_group_email" {
  description = "Cloud Identity / Google group whose members may reach the frontend through IAP (granted roles/iap.httpsResourceAccessor). Example: investment-analysts@malik-llc.example"
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.analyst_group_email))
    error_message = "analyst_group_email must be a group email address, e.g. investment-analysts@example.com."
  }
}

variable "backend_invoker_iam_disabled" {
  description = <<-EOT
    Disable the Cloud Run invoker IAM check on the backend. Default true because
    the stock nginx frontend proxy cannot mint Google-signed ID tokens; the backend
    is then protected by internal-only ingress (VPC traffic only) PLUS mandatory
    IAP JWT verification in the application (REQUIRE_IAP=true rejects any request
    without a valid IAP-signed assertion). Set to false only if you add an ID-token
    minting sidecar/entrypoint to the frontend.
  EOT
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------------
# Networking (frontend Direct VPC egress)
# ------------------------------------------------------------------------------

variable "network" {
  description = "VPC network (name or self link) used for the frontend's Direct VPC egress."
  type        = string
  default     = "default"
}

variable "subnetwork" {
  description = "Subnetwork (name or self link) in var.region used for Direct VPC egress. MUST have Private Google Access enabled so *.run.app calls to the internal backend route privately."
  type        = string
  default     = "default"
}

# ------------------------------------------------------------------------------
# Container images (Cloud Build owns image rollout; see README)
# ------------------------------------------------------------------------------

variable "backend_image" {
  description = "Initial backend container image. Defaults to <region>-docker.pkg.dev/<project>/investment-analyst/investment-analyst-backend:latest. Changes are ignored after creation (Cloud Build deploys new images)."
  type        = string
  default     = null
}

variable "frontend_image" {
  description = "Initial frontend container image. Defaults to <region>-docker.pkg.dev/<project>/investment-analyst/investment-analyst-frontend:latest. Changes are ignored after creation (Cloud Build deploys new images)."
  type        = string
  default     = null
}

# ------------------------------------------------------------------------------
# Backend runtime
# ------------------------------------------------------------------------------

variable "backend_service_name" {
  description = "Cloud Run service name for the FastAPI/ADK backend."
  type        = string
  default     = "investment-analyst-backend"
}

variable "backend_cpu" {
  description = "CPU limit for the backend container."
  type        = string
  default     = "2"
}

variable "backend_memory" {
  description = "Memory limit for the backend container."
  type        = string
  default     = "2Gi"
}

variable "backend_min_instances" {
  description = "Minimum backend instances (0 = scale to zero)."
  type        = number
  default     = 0
}

variable "backend_max_instances" {
  description = "Maximum backend instances."
  type        = number
  default     = 5
}

variable "backend_concurrency" {
  description = "Maximum concurrent requests per backend instance. Agent runs are long-lived and memory heavy, so keep this modest."
  type        = number
  default     = 20
}

variable "router_model" {
  description = "ANALYST_ROUTER_MODEL — orchestrator and data-gatherer agents."
  type        = string
  default     = "gemini-3.5-flash"
}

variable "reasoning_model" {
  description = "ANALYST_REASONING_MODEL — Financial Analyst synthesis agent."
  type        = string
  default     = "gemini-2.5-pro"
}

variable "sec_user_agent" {
  description = "SEC_USER_AGENT — required by the SEC EDGAR fair-access policy (company name + contact email)."
  type        = string
  default     = "MALIK LLC Investment Analyst admin@malik-llc.example"
}

variable "prompt_version" {
  description = "PROMPT_VERSION — versioned prompt set the backend loads."
  type        = string
  default     = "v1"
}

variable "agent_engine_id" {
  description = <<-EOT
    Vertex AI Agent Engine (reasoning engine) resource ID used for managed ADK
    sessions. When set, the backend uses SESSION_BACKEND=vertex so multi-turn
    conversations survive Cloud Run autoscaling; when empty, sessions are
    per-instance (SESSION_BACKEND=memory, fine for a single dev instance).
  EOT
  type        = string
  default     = ""
}

variable "frontend_attach_id_token" {
  description = <<-EOT
    Make the frontend nginx container fetch Google-signed ID tokens from the
    metadata server (audience = backend URL) and attach them to proxied calls.
    Set true together with backend_invoker_iam_disabled = false to keep Cloud
    Run's invoker IAM check on the backend.
  EOT
  type        = bool
  default     = false
}

variable "log_level" {
  description = "LOG_LEVEL for the backend structured logger."
  type        = string
  default     = "INFO"
}

variable "model_armor_template" {
  description = "Optional Model Armor template resource name (projects/P/locations/L/templates/T). Empty string disables Model Armor (no API enablement, no IAM grant)."
  type        = string
  default     = ""

  validation {
    condition     = var.model_armor_template == "" || can(regex("^projects/[^/]+/locations/[^/]+/templates/[^/]+$", var.model_armor_template))
    error_message = "model_armor_template must be empty or of the form projects/P/locations/L/templates/T."
  }
}

# ------------------------------------------------------------------------------
# Frontend runtime
# ------------------------------------------------------------------------------

variable "frontend_service_name" {
  description = "Cloud Run service name for the nginx/React frontend (also used to build the IAP audience)."
  type        = string
  default     = "investment-analyst-frontend"
}

variable "frontend_cpu" {
  description = "CPU limit for the frontend container."
  type        = string
  default     = "1"
}

variable "frontend_memory" {
  description = "Memory limit for the frontend container."
  type        = string
  default     = "512Mi"
}

variable "frontend_min_instances" {
  description = "Minimum frontend instances (0 = scale to zero)."
  type        = number
  default     = 0
}

variable "frontend_max_instances" {
  description = "Maximum frontend instances."
  type        = number
  default     = 3
}

# ------------------------------------------------------------------------------
# Data stores
# ------------------------------------------------------------------------------

variable "create_firestore_database" {
  description = "Create the Firestore Native `(default)` database. Set to false if it already exists in the project (a project can only have one `(default)` database)."
  type        = bool
  default     = true
}

variable "firestore_database" {
  description = "Firestore database id the backend uses (FIRESTORE_DATABASE)."
  type        = string
  default     = "(default)"
}

variable "firestore_location" {
  description = "Firestore location (regional, e.g. us-central1, or multi-region, e.g. nam5). Immutable after creation."
  type        = string
  default     = "us-central1"
}

variable "firestore_collection" {
  description = "Firestore collection for reports and feedback (FIRESTORE_COLLECTION)."
  type        = string
  default     = "analyst_reports"
}

variable "bigquery_dataset_id" {
  description = "BigQuery dataset for usage telemetry and audit log."
  type        = string
  default     = "analyst_telemetry"
}

variable "bigquery_location" {
  description = "BigQuery dataset location. Immutable after creation."
  type        = string
  default     = "us-central1"
}

variable "bigquery_partition_expiration_days" {
  description = "Optional partition expiration (days) for telemetry tables. null keeps data indefinitely."
  type        = number
  default     = null
}

variable "grant_bigquery_job_user" {
  description = "Grant the backend SA project-level roles/bigquery.jobUser. Not needed for streaming inserts / Storage Write API; enable only if the backend runs query or load jobs."
  type        = bool
  default     = false
}

variable "alpha_vantage_secret_id" {
  description = "Secret Manager secret id holding the Alpha Vantage API key. Terraform creates the container only; add the value out-of-band with gcloud."
  type        = string
  default     = "alpha-vantage-api-key"
}

# ------------------------------------------------------------------------------
# Artifact Registry / CI-CD
# ------------------------------------------------------------------------------

variable "artifact_registry_repository_id" {
  description = "Artifact Registry Docker repository id."
  type        = string
  default     = "investment-analyst"
}

variable "enable_github_trigger" {
  description = "Create a Cloud Build trigger on pushes to the main branch of a GitHub repository. Requires the Cloud Build GitHub App to be installed/connected for the repo first."
  type        = bool
  default     = false
}

variable "github_owner" {
  description = "GitHub organisation/user owning the repository (used when enable_github_trigger = true)."
  type        = string
  default     = ""
}

variable "github_repo" {
  description = "GitHub repository name (used when enable_github_trigger = true)."
  type        = string
  default     = ""
}

variable "github_branch_regex" {
  description = "Branch regex that triggers a build."
  type        = string
  default     = "^main$"
}
