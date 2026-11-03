# ==============================================================================
# BigQuery — token/latency telemetry and access audit trail
# ==============================================================================

resource "google_bigquery_dataset" "telemetry" {
  project       = var.project_id
  dataset_id    = var.bigquery_dataset_id
  friendly_name = "Investment Analyst telemetry"
  description   = "Per-request token usage, latency and access audit events emitted by the Investment Analyst backend."
  location      = var.bigquery_location

  # Prevent `terraform destroy` from wiping telemetry when deletion protection is on.
  delete_contents_on_destroy = !var.deletion_protection

  depends_on = [google_project_service.enabled]
}

resource "google_bigquery_table" "usage_events" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.telemetry.dataset_id
  table_id            = "usage_events"
  description         = "One row per agent model call: token counts, latency and tools invoked."
  deletion_protection = var.deletion_protection

  time_partitioning {
    type          = "DAY"
    field         = "ts"
    expiration_ms = var.bigquery_partition_expiration_days == null ? null : var.bigquery_partition_expiration_days * 86400000
  }

  clustering = ["session_id", "model"]

  schema = jsonencode([
    { name = "ts", type = "TIMESTAMP", mode = "REQUIRED", description = "Event timestamp (UTC)." },
    { name = "session_id", type = "STRING", mode = "NULLABLE", description = "Conversation session id." },
    { name = "report_id", type = "STRING", mode = "NULLABLE", description = "Report (response) id, uuid4." },
    { name = "user", type = "STRING", mode = "NULLABLE", description = "Authenticated user email (from IAP) or local-dev." },
    { name = "model", type = "STRING", mode = "NULLABLE", description = "Gemini model id." },
    { name = "agent", type = "STRING", mode = "NULLABLE", description = "ADK agent name." },
    { name = "prompt_tokens", type = "INT64", mode = "NULLABLE", description = "Prompt token count." },
    { name = "output_tokens", type = "INT64", mode = "NULLABLE", description = "Output token count." },
    { name = "total_tokens", type = "INT64", mode = "NULLABLE", description = "Total token count." },
    { name = "ttft_ms", type = "FLOAT64", mode = "NULLABLE", description = "Time to first token (ms)." },
    { name = "total_ms", type = "FLOAT64", mode = "NULLABLE", description = "Total request latency (ms)." },
    { name = "tools_called", type = "STRING", mode = "NULLABLE", description = "JSON-encoded list of {agent, tool, args}." },
    { name = "tickers", type = "STRING", mode = "REPEATED", description = "Tickers referenced by the request." },
  ])
}

resource "google_bigquery_table" "audit_log" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.telemetry.dataset_id
  table_id            = "audit_log"
  description         = "Access audit trail: who asked for what, and the outcome."
  deletion_protection = var.deletion_protection

  time_partitioning {
    type          = "DAY"
    field         = "ts"
    expiration_ms = var.bigquery_partition_expiration_days == null ? null : var.bigquery_partition_expiration_days * 86400000
  }

  clustering = ["user", "action"]

  schema = jsonencode([
    { name = "ts", type = "TIMESTAMP", mode = "REQUIRED", description = "Event timestamp (UTC)." },
    { name = "user", type = "STRING", mode = "NULLABLE", description = "Authenticated user email (from IAP) or local-dev." },
    { name = "action", type = "STRING", mode = "NULLABLE", description = "Action, e.g. chat, chat_stream, feedback." },
    { name = "tickers", type = "STRING", mode = "REPEATED", description = "Tickers referenced by the request." },
    { name = "session_id", type = "STRING", mode = "NULLABLE", description = "Conversation session id." },
    { name = "report_id", type = "STRING", mode = "NULLABLE", description = "Report (response) id, uuid4." },
    { name = "status", type = "STRING", mode = "NULLABLE", description = "Outcome, e.g. ok, blocked, error." },
  ])
}

# Dataset-scoped (not project-wide) write access for the backend.
resource "google_bigquery_dataset_iam_member" "backend_data_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.telemetry.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.backend.member
}
