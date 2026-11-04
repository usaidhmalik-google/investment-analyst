# ==============================================================================
# Cloud Monitoring: Alert Policies, Log-Based Metrics, and Uptime Checks
# ==============================================================================

variable "enable_monitoring_alerts" {
  description = "Create Cloud Monitoring alert policies and log-based metrics for SLA enforcement."
  type        = bool
  default     = false
}

variable "alert_notification_email" {
  description = "Email address for Cloud Monitoring incident notifications (used when enable_monitoring_alerts = true)."
  type        = string
  default     = "oncall@malik-llc.example"
}

resource "google_monitoring_notification_channel" "oncall_email" {
  count        = var.enable_monitoring_alerts ? 1 : 0
  project      = var.project_id
  display_name = "Investment Analyst On-Call (${var.environment})"
  type         = "email"

  labels = {
    email_address = var.alert_notification_email
  }
}

# Log-based metric counting prompt-injection or Model Armor blocks
resource "google_logging_metric" "guardrail_blocks" {
  count       = var.enable_monitoring_alerts ? 1 : 0
  project     = var.project_id
  name        = "investment_analyst_${var.environment}_guardrail_blocks"
  description = "Count of prompt injection or Model Armor guardrail blocks on the backend."
  filter      = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.backend_service_name}"
    jsonPayload.telemetry.status="blocked"
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Analyst Guardrail Blocks (${var.environment})"
  }
}

# Alert Policy 1: Cloud Run Backend 5xx Error Rate > 2% over 5 minutes
resource "google_monitoring_alert_policy" "backend_error_rate" {
  count        = var.enable_monitoring_alerts ? 1 : 0
  project      = var.project_id
  display_name = "[${upper(var.environment)}] Investment Analyst Backend 5xx Error Rate > 2%"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run 5xx response count above threshold"
    condition_threshold {
      filter          = <<-EOT
        resource.type = "cloud_run_revision" AND
        resource.labels.service_name = "${var.backend_service_name}" AND
        metric.type = "run.googleapis.com/request_count" AND
        metric.labels.response_code_class = "5xx"
      EOT
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 2

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.oncall_email[0].id
  ]

  documentation {
    content   = "Backend 5xx rate exceeded SLA threshold. Follow docs/OPERATIONS_RUNBOOK.md SEV-1 playbook and inspect Cloud Run logs or roll back canary traffic via scripts/deploy_canary.sh."
    mime_type = "text/markdown"
  }
}

# Alert Policy 2: Cloud Run Backend p95 Request Latency > 30s
resource "google_monitoring_alert_policy" "backend_latency_sla" {
  count        = var.enable_monitoring_alerts ? 1 : 0
  project      = var.project_id
  display_name = "[${upper(var.environment)}] Investment Analyst Backend p95 Latency > 30s"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run p95 request latencies > 30000 ms"
    condition_threshold {
      filter          = <<-EOT
        resource.type = "cloud_run_revision" AND
        resource.labels.service_name = "${var.backend_service_name}" AND
        metric.type = "run.googleapis.com/request_latencies"
      EOT
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 30000

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.oncall_email[0].id
  ]

  documentation {
    content   = "Backend p95 latency exceeded 30s SLA. Check /api/v1/metrics for tripped provider circuit breakers (Yahoo/Alpha Vantage/SEC EDGAR) or Vertex AI quota throttling."
    mime_type = "text/markdown"
  }
}
