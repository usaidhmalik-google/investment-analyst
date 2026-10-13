# ==============================================================================
# Cloud Run v2 services
# ==============================================================================
#
#   user ──HTTPS──▶ IAP ──▶ investment-analyst-frontend (nginx, ingress ALL,
#                            IAP-protected, Direct VPC egress ALL_TRAFFIC)
#                                   │  /api/*, /healthz  (via VPC + PGA => "internal")
#                                   ▼
#                           investment-analyst-backend (FastAPI + ADK,
#                            ingress INTERNAL_ONLY, run.invoker = frontend SA)
#
# Image rollout is owned by Cloud Build (`gcloud run deploy --image ...`), so
# Terraform ignores image (and gcloud client metadata) drift after creation.
# All other configuration — env, scaling, probes, IAM — stays in Terraform.

# ------------------------------------------------------------------------------
# Backend: FastAPI + Google ADK
# ------------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "backend" {
  project  = var.project_id
  name     = var.backend_service_name
  location = var.region

  description = "Investment Analyst Agent API (FastAPI + Google ADK)."

  # Reachable only from VPC networks in this project (incl. the frontend's
  # Direct VPC egress). No public ingress.
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  # See var.backend_invoker_iam_disabled. Default true => internal-only ingress
  # + application-level IAP JWT verification (REQUIRE_IAP=true) gate every call.
  invoker_iam_disabled = var.backend_invoker_iam_disabled

  deletion_protection = var.deletion_protection

  template {
    service_account = google_service_account.backend.email
    timeout         = "300s"

    max_instance_request_concurrency = var.backend_concurrency

    labels = local.labels

    scaling {
      min_instance_count = var.backend_min_instances
      max_instance_count = var.backend_max_instances
    }

    containers {
      name  = "backend"
      image = local.backend_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.backend_cpu
          memory = var.backend_memory
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      # --- Google Cloud / Vertex AI -------------------------------------------
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }

      # --- Models ---------------------------------------------------------------
      env {
        name  = "ANALYST_ROUTER_MODEL"
        value = var.router_model
      }
      env {
        name  = "ANALYST_REASONING_MODEL"
        value = var.reasoning_model
      }

      # --- Market data ----------------------------------------------------------
      # Version RESOURCE NAME, not the key. The backend reads it at runtime.
      env {
        name  = "ALPHA_VANTAGE_SECRET"
        value = "${google_secret_manager_secret.alpha_vantage.id}/versions/latest"
      }
      env {
        name  = "SEC_USER_AGENT"
        value = var.sec_user_agent
      }

      # --- Persistence & telemetry ---------------------------------------------
      env {
        name  = "PERSISTENCE_BACKEND"
        value = "firestore"
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = var.firestore_database
      }
      env {
        name  = "FIRESTORE_COLLECTION"
        value = var.firestore_collection
      }
      env {
        name  = "BQ_USAGE_TABLE"
        value = local.bq_usage_table
      }
      env {
        name  = "BQ_AUDIT_TABLE"
        value = local.bq_audit_table
      }
      env {
        name  = "ENABLE_CLOUD_TRACE"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      # --- Security ---------------------------------------------------------------
      env {
        name  = "REQUIRE_IAP"
        value = "true"
      }
      env {
        name  = "IAP_AUDIENCE"
        value = local.iap_audience
      }
      env {
        name  = "MODEL_ARMOR_TEMPLATE"
        value = var.model_armor_template
      }
      env {
        name  = "PROMPT_VERSION"
        value = var.prompt_version
      }
      env {
        name  = "SESSION_BACKEND"
        value = var.agent_engine_id != "" ? "vertex" : "memory"
      }
      env {
        name  = "AGENT_ENGINE_ID"
        value = var.agent_engine_id
      }

      startup_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 0
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 24 # up to ~2 minutes for ADK/model client init
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        period_seconds    = 30
        timeout_seconds   = 5
        failure_threshold = 3
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image, # rolled out by Cloud Build
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.enabled,
    google_project_iam_member.backend,
    google_secret_manager_secret_iam_member.backend_alpha_vantage_accessor,
    google_bigquery_dataset_iam_member.backend_data_editor,
  ]
}

# The backend's ingress is INTERNAL_ONLY, which restricts *where* requests can
# come from (the VPC) but not *who* may call. Cloud Run's invoker IAM check is
# the second layer: only the frontend's identity may invoke the backend, so
# another workload that happens to share the VPC cannot call the agent API.
# (Requires the frontend proxy to attach an ID token whose audience is the
# backend URL — see README "Frontend → backend authentication".)
resource "google_cloud_run_v2_service_iam_member" "backend_invoker_frontend" {
  project  = var.project_id
  location = google_cloud_run_v2_service.backend.location
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = google_service_account.frontend.member
}

# ------------------------------------------------------------------------------
# Frontend: nginx serving the React build, IAP-protected
# ------------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "frontend" {
  provider = google-beta

  project  = var.project_id
  name     = var.frontend_service_name
  location = var.region

  description = "Investment Analyst Agent web UI (nginx + React), protected by IAP."

  # Public endpoint, but every request is authenticated by IAP before it
  # reaches the container (direct Cloud Run IAP integration).
  ingress      = "INGRESS_TRAFFIC_ALL"
  launch_stage = "BETA"
  iap_enabled  = true

  deletion_protection = var.deletion_protection

  template {
    service_account = google_service_account.frontend.email
    timeout         = "300s" # long-lived SSE streams from /api/chat/stream

    labels = local.labels

    scaling {
      min_instance_count = var.frontend_min_instances
      max_instance_count = var.frontend_max_instances
    }

    # Direct VPC egress: ALL outbound traffic (including to *.run.app) goes into
    # the VPC, so calls to the INTERNAL_ONLY backend are classified as internal.
    # The subnet must have Private Google Access enabled.
    vpc_access {
      network_interfaces {
        network    = var.network
        subnetwork = var.subnetwork
      }
      egress = "ALL_TRAFFIC"
    }

    containers {
      name  = "frontend"
      image = local.frontend_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.frontend_cpu
          memory = var.frontend_memory
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }
      env {
        # Mint ID tokens for the backend invoker check (pair with backend_invoker_iam_disabled = false).
        name  = "BACKEND_ID_TOKEN"
        value = var.frontend_attach_id_token ? "true" : "false"
      }

      # TCP probe on purpose: nginx proxies /healthz to the backend, so an HTTP
      # probe would couple frontend health to backend cold starts.
      startup_probe {
        tcp_socket {
          port = 8080
        }
        period_seconds    = 3
        timeout_seconds   = 2
        failure_threshold = 10
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image, # rolled out by Cloud Build
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.enabled]
}

# IAP's service agent invokes the frontend on behalf of authenticated users.
resource "google_cloud_run_v2_service_iam_member" "frontend_invoker_iap" {
  project  = var.project_id
  location = google_cloud_run_v2_service.frontend.location
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_project_service_identity.iap.email}"
}

# RBAC: only members of the analyst group pass IAP.
resource "google_iap_web_cloud_run_service_iam_member" "frontend_analysts" {
  project                = var.project_id
  location               = google_cloud_run_v2_service.frontend.location
  cloud_run_service_name = google_cloud_run_v2_service.frontend.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = "group:${var.analyst_group_email}"
}

# ------------------------------------------------------------------------------
# Cloud Build may roll out new revisions of these two services only.
# ------------------------------------------------------------------------------

resource "google_cloud_run_v2_service_iam_member" "build_developer" {
  for_each = {
    backend  = google_cloud_run_v2_service.backend.name
    frontend = google_cloud_run_v2_service.frontend.name
  }

  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.developer"
  member   = google_service_account.build.member
}
