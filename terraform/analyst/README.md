# Investment Analyst Agent — Infrastructure (Terraform)

Terraform root module for the Investment Analyst Agent on Google Cloud. It's
**separate from the Aegis module** in `../` and has its own state and provider
config. Run every command from `terraform/analyst/`.

Service contract (env vars, endpoints, topology): [`docs/API_CONTRACT.md`](../../docs/API_CONTRACT.md).

## What gets created

| Area | Resources | File |
| --- | --- | --- |
| APIs | run, aiplatform, secretmanager, firestore, bigquery, artifactregistry, cloudbuild, iap, cloudtrace, logging, monitoring, compute, iam, cloudresourcemanager (+ modelarmor if a template is set) | `apis.tf` |
| Identities | `investment-analyst-sa` (backend), `investment-analyst-frontend-sa`, `investment-analyst-build-sa`, IAP service agent | `iam.tf` |
| Secrets | `alpha-vantage-api-key` (container only, no value) + secret-level accessor for the backend | `secrets.tf` |
| Firestore | Native `(default)` database (optional, PITR on) | `firestore.tf` |
| BigQuery | `analyst_telemetry.usage_events`, `analyst_telemetry.audit_log` (DAY-partitioned on `ts`) + dataset-level `dataEditor` for the backend | `bigquery.tf` |
| Registry | Artifact Registry Docker repo `investment-analyst` with cleanup policies | `artifact_registry.tf` |
| Compute | Cloud Run v2 `investment-analyst-backend` (internal-only) and `investment-analyst-frontend` (IAP, Direct VPC egress) | `cloud_run.tf` |
| CI/CD | Build SA grants; optional GitHub push trigger | `iam.tf`, `cloud_run.tf`, `cloudbuild.tf`, `../../cloudbuild.yaml` |

Every resource that supports labels gets `app=investment-analyst`,
`managed_by=terraform`, `env=<var.environment>` (provider `default_labels`, plus
revision labels on Cloud Run).

## Architecture

```
analyst (browser)
   │ HTTPS
   ▼
Identity-Aware Proxy ── checks roles/iap.httpsResourceAccessor (var.analyst_group_email)
   │ invokes as IAP service agent (roles/run.invoker)
   ▼
investment-analyst-frontend   Cloud Run, ingress ALL, iap_enabled, SA investment-analyst-frontend-sa
   │ nginx proxies /api/* and /healthz to $BACKEND_URL
   │ Direct VPC egress (ALL_TRAFFIC) → subnet with Private Google Access
   ▼
investment-analyst-backend    Cloud Run, ingress INTERNAL_ONLY, SA investment-analyst-sa
   ├─ Vertex AI Gemini (router + reasoning models), Model Armor (optional)
   ├─ Firestore (reports, feedback)        ├─ BigQuery (usage_events, audit_log)
   ├─ Secret Manager (Alpha Vantage key)   └─ Cloud Trace / Logging / Monitoring
   └─ Internet egress: Yahoo Finance, Alpha Vantage, SEC EDGAR
```

### Network: Private Google Access is required

The backend's ingress is `INGRESS_TRAFFIC_INTERNAL_ONLY`. Cloud Run only treats a
request as internal if it comes from a VPC network in the same project (or
through a Shared VPC / VPC-SC perimeter it trusts). The frontend uses **Direct
VPC egress with `egress = "ALL_TRAFFIC"`**, so its calls to the backend's
`*.run.app` URL leave through `var.subnetwork`.

For those calls to reach Google APIs over the VPC, **Private Google Access has to
be on** for that subnet. Without it, the requests fail. Here's how to check and
enable it:

```bash
gcloud compute networks subnets describe default --region=us-central1 \
  --format='value(privateIpGoogleAccess)'
gcloud compute networks subnets update default --region=us-central1 \
  --enable-private-ip-google-access
```

With `ALL_TRAFFIC` egress the frontend can't reach the public internet unless
you add Cloud NAT. That's fine because nginx only talks to the backend. The
backend has no VPC egress, so it uses Cloud Run's default internet egress for the
market-data APIs.

### Frontend → backend authentication

Ingress settings control **where** a request can come from; they don't control
**who** is calling. The backend therefore layers two controls:

1. **Network:** `INGRESS_TRAFFIC_INTERNAL_ONLY` — only traffic from this project's
   VPC (the frontend's Direct VPC egress) can reach it. No public ingress.
2. **Identity:** the backend verifies the IAP-signed `X-Goog-IAP-JWT-Assertion`
   that nginx forwards (`REQUIRE_IAP=true`, `IAP_AUDIENCE`). Requests without a
   valid assertion get HTTP 401, so every call is tied to an authenticated analyst
   in `analyst_group_email`.

By default the Cloud Run invoker IAM check on the backend is **disabled**
(`backend_invoker_iam_disabled = true`). For a third layer, set both:

```hcl
frontend_attach_id_token     = true   # nginx mints ID tokens (audience = backend URL)
backend_invoker_iam_disabled = false  # Cloud Run requires roles/run.invoker + ID token
```

The frontend image's `25-backend-id-token.sh` fetches the token from the
metadata server at startup (and fails the container if it can't), writes it to
an nginx include, and refreshes it every 20 minutes with a graceful reload.
Tokens are valid for about an hour. If you enable this, consider setting
`cpu_idle = false` on the frontend, because CPU throttling between requests can
delay the background refresh.

### Conversation sessions

ADK sessions are in memory unless you set `agent_engine_id`. With in-memory
sessions, a follow-up turn that Cloud Run routes to a different instance starts a
new conversation. For production, create a Vertex AI Agent Engine (reasoning engine)
instance and set `agent_engine_id`. The backend then uses `SESSION_BACKEND=vertex`
(covered by `roles/aiplatform.user`). `SESSION_BACKEND=database` with a SQLAlchemy
URL (e.g. Cloud SQL Postgres) is also supported by the app.

### Identity per agent (honest version)

ADK runs all the agents (root orchestrator, data gatherer, SEC filing parser,
strategy evaluator, financial analyst) **in one process**, inside one Cloud Run service. Cloud Run gives a
service exactly one runtime identity, so **all agents share
`investment-analyst-sa`**. Its permissions are the union of what the agents need.
Agent-level attribution comes from the `agent` column in `usage_events`,
structured logs and trace spans, not from IAM.

We don't create per-agent service accounts because nothing would use them. If
you need hard per-agent isolation (for example, only the data gatherer may read
the Alpha Vantage secret), split it like this:

1. Move each agent that needs its own privileges into a separate Cloud Run
   service (or Vertex AI Agent Engine deployment) with a dedicated SA. Have the
   orchestrator call it over HTTP or A2A with an ID token.
2. Move the matching grants from `google_service_account.backend` to the new SA
   (for example, the secret accessor to a gatherer SA, BigQuery `dataEditor` to
   a telemetry SA).
3. Give the orchestrator SA `roles/run.invoker` on each agent service only.

Calling `impersonate`/`generateAccessToken` per tool call inside one process
does **not** isolate anything, because the runtime SA would need permission to
mint every agent's token.

### Least-privilege summary

| Principal | Role | Scope |
| --- | --- | --- |
| backend SA | `aiplatform.user`, `datastore.user`, `logging.logWriter`, `cloudtrace.agent`, `monitoring.metricWriter` | project |
| backend SA | `modelarmor.user` | project, only if `model_armor_template` is set |
| backend SA | `bigquery.jobUser` | project, only if `grant_bigquery_job_user = true` (not needed for streaming inserts) |
| backend SA | `bigquery.dataEditor` | dataset `analyst_telemetry` |
| backend SA | `secretmanager.secretAccessor` | secret `alpha-vantage-api-key` |
| frontend SA | `run.invoker` | backend service |
| IAP service agent | `run.invoker` | frontend service |
| `group:<analyst_group_email>` | `iap.httpsResourceAccessor` | frontend service (IAP) |
| build SA | `artifactregistry.writer` | repo `investment-analyst` |
| build SA | `run.developer` | the two services |
| build SA | `iam.serviceAccountUser` | the two runtime SAs |
| build SA | `logging.logWriter` | project |

`roles/datastore.user` is project-scoped because Firestore has no
database-level IAM binding resource. If you need to narrow it, add an IAM
condition on `resource.name` for the database.

## Deploy

Prerequisites:

* `gcloud` authenticated as someone with Owner, or Project IAM Admin plus admin
  on the services above
* Terraform ≥ 1.5. A pinned binary can live in `.tools/terraform/` (gitignored).
* A Google group for analysts
* Private Google Access on the subnet (see above)

```bash
cd terraform/analyst
cp terraform.tfvars.example terraform.tfvars   # set analyst_group_email etc.

gcloud auth application-default login
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

### 1. Add the Alpha Vantage key (out-of-band, never in Terraform)

```bash
printf '%s' "$ALPHA_VANTAGE_API_KEY" | gcloud secrets versions add alpha-vantage-api-key \
  --data-file=- --project="$PROJECT_ID"
```

The backend gets `ALPHA_VANTAGE_SECRET=projects/<p>/secrets/alpha-vantage-api-key/versions/latest`
and reads the value at runtime.

### 2. Build and push the first images

The Cloud Run services point at
`us-central1-docker.pkg.dev/<project>/investment-analyst/investment-analyst-{backend,frontend}:latest`.
If no image exists yet, the first `apply` creates every other resource and then
fails on the Cloud Run services. You can avoid that in two ways:

* **Bootstrap order:** run
  `terraform apply -target=google_artifact_registry_repository.images -target=google_service_account.build -target=google_artifact_registry_repository_iam_member.build_writer`,
  push the images (below), then run the full `terraform apply`.
* **Placeholder:** pass `-var backend_image=us-docker.pkg.dev/cloudrun/container/hello`
  (same for the frontend) on the first apply, then let Cloud Build roll out the
  real images.

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
REPO=us-central1-docker.pkg.dev/$PROJECT_ID/investment-analyst
docker build -t $REPO/investment-analyst-backend:latest  ../../investment-analyst
docker build -t $REPO/investment-analyst-frontend:latest ../../frontend
docker push $REPO/investment-analyst-backend:latest
docker push $REPO/investment-analyst-frontend:latest
```

Or run the full pipeline from the repo root:

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=SHORT_SHA=$(git rev-parse --short HEAD) \
  --service-account="$(terraform -chdir=terraform/analyst output -raw build_service_account)" \
  --default-buckets-behavior=regional-user-owned-bucket .
```

The account running `gcloud builds submit` needs `roles/iam.serviceAccountUser`
on the build SA. If there's no `.gcloudignore`, gcloud falls back to
`.gitignore`, which keeps `.venv/`, `node_modules/` and `.tools/` out of the
upload.

### 3. CI trigger (optional)

Connect the GitHub repo to Cloud Build first (Console → Cloud Build → Triggers →
Connect repository; this is a one-time OAuth step). Then set:

```hcl
enable_github_trigger = true
github_owner          = "malik-llc"
github_repo           = "investment-analyst"
```

Pushes to `main` then run `cloudbuild.yaml` as `investment-analyst-build-sa`.

### 4. Open the app

`terraform output frontend_url`. Sign in with an account in
`analyst_group_email`. Direct Cloud Run IAP uses a Google-managed OAuth client,
which works for users in your organization. External users need a custom OAuth
client/brand.

## Who owns what: Terraform vs Cloud Build

Terraform owns **configuration**: env vars, scaling, probes, ingress, IAP, VPC,
IAM. Cloud Build owns **image rollout**: `gcloud run deploy --image <tag>` only.
To keep them from fighting, both Cloud Run services have:

```hcl
lifecycle {
  ignore_changes = [template[0].containers[0].image, client, client_version]
}
```

Because of this, changing `backend_image`/`frontend_image` after the first apply
has **no effect**. Deploy new images through Cloud Build (or `gcloud run deploy`).
Env, scaling and other config changes still go through `terraform apply`, which
creates a new revision that reuses the currently deployed image.

## Encryption

* **At rest:** Firestore, BigQuery, Secret Manager, Artifact Registry, Cloud
  Logging and Cloud Run are all encrypted by default with **Google-managed
  encryption keys (GMEK)**. You don't need to configure anything.
* **In transit:** All traffic is TLS. That covers browser → IAP → Cloud Run,
  frontend → backend (`https://*.run.app` over Private Google Access), and
  backend → Google APIs and external market-data APIs.
* **CMEK (if you need it):** create a Cloud KMS key ring and key in the same
  location as each resource, and grant each service agent
  `roles/cloudkms.cryptoKeyEncrypterDecrypter` on the key. Then set:
  `google_bigquery_dataset.default_encryption_configuration.kms_key_name`,
  `google_firestore_database.cmek_config.kms_key_name` (only at creation time),
  `google_secret_manager_secret.replication.user_managed.replicas[].customer_managed_encryption`
  (needs user-managed replication),
  `google_artifact_registry_repository.kms_key_name`, and
  `google_cloud_run_v2_service.template.encryption_key`. Most of these can't be
  changed in place after creation, so decide before production.

## Variables you must set

| Variable | Why |
| --- | --- |
| `analyst_group_email` | **Required** (no default): the IAP RBAC group |
| `project_id` | Defaults to `fde-investment-analyst-sandbox-dev` |
| `create_firestore_database` | Set to `false` if `(default)` already exists |
| `network` / `subnetwork` | If you're not using `default` (needs Private Google Access) |
| `model_armor_template` | Optional |
| `backend_invoker_iam_disabled` | Default `true`; set `false` together with `frontend_attach_id_token = true` |
| `frontend_attach_id_token` | nginx attaches metadata-server ID tokens to backend calls |
| `agent_engine_id` | Vertex AI Agent Engine ID for shared multi-instance sessions |
| `enable_github_trigger`, `github_owner`, `github_repo` | Optional CI trigger |

See `variables.tf` for everything else (models, scaling, CPU/memory, retention).

## Validation without touching a real project

```bash
../../.tools/terraform/terraform fmt -check -recursive
../../.tools/terraform/terraform init -backend=false
../../.tools/terraform/terraform validate
```
