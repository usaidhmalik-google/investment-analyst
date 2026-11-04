# ==============================================================================
# Network & Edge Security: Cloud Armor WAF Policy (Defense-in-Depth)
# ==============================================================================

variable "enable_cloud_armor" {
  description = "Create a Google Cloud Armor security policy with OWASP XSS/SQLi preconfigured rules and per-IP rate limiting."
  type        = bool
  default     = false
}

variable "cloud_armor_rate_limit_rpm" {
  description = "Per-IP rate-limit threshold (requests per minute) enforced by Cloud Armor when enable_cloud_armor = true."
  type        = number
  default     = 120
}

resource "google_compute_security_policy" "edge_waf" {
  count       = var.enable_cloud_armor ? 1 : 0
  project     = var.project_id
  name        = "investment-analyst-${var.environment}-waf"
  description = "Cloud Armor WAF policy protecting the Investment Analyst frontend LB (OWASP XSS/SQLi + rate limiting)."

  # Rule 1000: Per-IP rate limiting (429 Too Many Requests)
  rule {
    action   = "rate_based_ban"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action   = "allow"
      exceed_action    = "deny(429)"
      enforce_on_key   = "IP"
      ban_duration_sec = 300
      rate_limit_threshold {
        count        = var.cloud_armor_rate_limit_rpm
        interval_sec = 60
      }
    }
    description = "Rate-limit abusive client IPs exceeding ${var.cloud_armor_rate_limit_rpm} req/min."
  }

  # Rule 2000: Block OWASP Cross-Site Scripting (XSS)
  rule {
    action   = "deny(403)"
    priority = 2000
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('xss-v33-stable')"
      }
    }
    description = "Block OWASP ModSecurity CRS XSS payloads."
  }

  # Rule 2100: Block OWASP SQL Injection (SQLi)
  rule {
    action   = "deny(403)"
    priority = 2100
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('sqli-v33-stable')"
      }
    }
    description = "Block OWASP ModSecurity CRS SQLi payloads."
  }

  # Default Rule: Allow legitimate traffic through to IAP
  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default allow rule (authenticated downstream by Cloud IAP)."
  }
}
