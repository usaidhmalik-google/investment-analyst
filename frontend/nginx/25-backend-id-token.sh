#!/bin/sh
# Optional: attach a Google-signed ID token to every request proxied to the backend so the
# backend Cloud Run service can keep its invoker IAM check ON (terraform:
# backend_invoker_iam_disabled = false + frontend_attach_id_token = true).
#
# Enabled with BACKEND_ID_TOKEN=true. Writes `proxy_set_header Authorization ...` into
# /etc/nginx/snippets/backend-auth.conf (included by backend-proxy.conf) and refreshes it in the
# background every ${ID_TOKEN_REFRESH_SECONDS:-1200}s, gracefully reloading nginx (in-flight SSE
# streams finish on the old workers). Tokens are valid for ~60 minutes.

set -eu

SNIPPET=/etc/nginx/snippets/backend-auth.conf
: > "$SNIPPET"

if [ "${BACKEND_ID_TOKEN:-false}" != "true" ]; then
  echo "25-backend-id-token.sh: BACKEND_ID_TOKEN!=true, not attaching ID tokens"
  exit 0
fi

AUDIENCE="${ID_TOKEN_AUDIENCE:-${BACKEND_URL:-}}"
while [ "${AUDIENCE%/}" != "$AUDIENCE" ]; do AUDIENCE="${AUDIENCE%/}"; done
if [ -z "$AUDIENCE" ]; then
  echo "25-backend-id-token.sh: ERROR: BACKEND_URL/ID_TOKEN_AUDIENCE not set" >&2
  exit 1
fi
METADATA="http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${AUDIENCE}&format=full"

fetch_token() {
  token="$(wget -q -T 5 -O - --header 'Metadata-Flavor: Google' "$METADATA" 2>/dev/null || true)"
  case "$token" in
    ey*.*.*)
      tmp="${SNIPPET}.tmp"
      printf 'proxy_set_header Authorization "Bearer %s";\n' "$token" > "$tmp"
      mv "$tmp" "$SNIPPET"
      return 0 ;;
    *)
      echo "25-backend-id-token.sh: WARNING: could not fetch ID token from metadata server" >&2
      return 1 ;;
  esac
}

# Fail fast at startup: without a token every backend call would be rejected.
attempt=0
until fetch_token; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 5 ]; then
    echo "25-backend-id-token.sh: ERROR: giving up fetching ID token" >&2
    exit 1
  fi
  sleep 2
done
echo "25-backend-id-token.sh: attaching ID tokens for audience $AUDIENCE"

(
  while true; do
    sleep "${ID_TOKEN_REFRESH_SECONDS:-1200}"
    if fetch_token; then
      nginx -s reload 2>/dev/null || true
    fi
  done
) &
