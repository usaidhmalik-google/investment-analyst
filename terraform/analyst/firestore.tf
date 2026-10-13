# ==============================================================================
# Firestore (Native mode) — report + feedback persistence
# ==============================================================================
# A project can hold only one `(default)` database. If it already exists, set
# create_firestore_database = false (or `terraform import` it).

resource "google_firestore_database" "default" {
  count = var.create_firestore_database ? 1 : 0

  project     = var.project_id
  name        = var.firestore_database
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  concurrency_mode            = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"

  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  delete_protection_state           = var.deletion_protection ? "DELETE_PROTECTION_ENABLED" : "DELETE_PROTECTION_DISABLED"

  # `terraform destroy` leaves the database (and its data) in place.
  deletion_policy = "ABANDON"

  depends_on = [google_project_service.enabled]
}
