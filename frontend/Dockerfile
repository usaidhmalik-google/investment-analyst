# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Investment Analyst frontend: Vite build -> nginx static server + API proxy.
# ---------------------------------------------------------------------------

# ---- Build stage ----------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---- Runtime stage --------------------------------------------------------
FROM nginx:alpine AS runtime

# The official image runs envsubst over /etc/nginx/templates/*.template into
# /etc/nginx/conf.d/ at startup (docker-entrypoint.d/20-envsubst-on-templates.sh).
# Only variables listed in NGINX_ENVSUBST_FILTER are substituted so nginx's own
# $variables are left intact.
# BACKEND_URL has no default and must be supplied at run time (the container
# fails fast otherwise). Because the backend host is resolved by nginx's DNS
# `resolver` (not /etc/hosts), use a DNS name or an IP literal, not "localhost".
ENV PORT=8080 \
    BACKEND_HOST="" \
    BACKEND_SNI="" \
    DNS_RESOLVER="" \
    BACKEND_ID_TOKEN="false" \
    NGINX_ENVSUBST_FILTER="^(PORT|BACKEND_URL|BACKEND_HOST|BACKEND_SNI|DNS_RESOLVER)$"

RUN rm -f /etc/nginx/conf.d/default.conf

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/backend-proxy.conf nginx/security-headers.conf /etc/nginx/snippets/
# Derives BACKEND_HOST / BACKEND_SNI / DNS_RESOLVER before the template is rendered
# (scripts run in lexical order; 15 < 20-envsubst-on-templates.sh).
COPY --chmod=0755 nginx/15-backend-host.envsh /docker-entrypoint.d/15-backend-host.envsh
# Optional ID-token minting for the backend's Cloud Run invoker check (BACKEND_ID_TOKEN=true).
COPY --chmod=0755 nginx/25-backend-id-token.sh /docker-entrypoint.d/25-backend-id-token.sh
RUN touch /etc/nginx/snippets/backend-auth.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null "http://127.0.0.1:${PORT}/nginx-health" || exit 1
