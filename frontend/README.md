# Investment Analyst — Frontend

React 18 + TypeScript (strict) + Tailwind CSS + Vite chat UI for the MALIK LLC
Investment Analyst Agent. The binding API contract is
[`docs/API_CONTRACT.md`](../docs/API_CONTRACT.md).

## Features

- Chat UI with a strategy lens selector (None / Momentum / Value / Swing / Income → `strategy`).
- Streams `POST /api/chat/stream` via `fetch` + `ReadableStream` (custom SSE parser, since
  `EventSource` cannot POST): live **agent activity** timeline (`thought`), token streaming
  (`token`), replaced by the authoritative `final` `ChatResponse`. `error` events, HTTP errors,
  network failures and truncated streams are surfaced inline; the user can **Stop** a stream.
- Multi-turn: `session_id` from the `session`/`final` event is sent on follow-ups; **New chat** resets it.
- Markdown (react-markdown + remark-gfm). Inline citation ids such as `[Q:NVDA]` (contract regex)
  become numbered superscript chips that scroll to and highlight the entry in the **Sources** panel
  (title, source, as-of, link). Ids inside code spans are left alone; ids without a matching
  citation are flagged.
- Fact-check badge (verified / N unverified numbers, accuracy %), latency stats (first thought,
  first token, total — server values, falling back to client-measured), blocked-response styling.
- 👍 / 👎 with optional comment → `POST /api/feedback`.
- Dark / light theme (persisted), keyboard friendly (Enter sends, Shift+Enter newline), ARIA labels.

## Layout

```
src/
  types.ts              # Contract types (ChatRequest/Response, stream events, UI state)
  api/client.ts         # Typed fetch client: streamChat, chat, sendFeedback, getConfig
  api/sse.ts            # Incremental SSE parser + typed event decoding
  lib/citations.ts      # Citation regex, splitting/ordering, remark plugin
  lib/format.ts         # ms / % / label formatting
  state/chatReducer.ts  # Pure chat state machine
  state/useChat.ts      # Streaming orchestration hook (abort, session handling)
  components/           # UI components
nginx/                  # Production nginx template + snippets
```

## Development

Node 20+ is required. On machines without Node, install it locally in the repo root
(`.tools/` is git-ignored):

```bash
cd ..   # repo root
mkdir -p .tools && cd .tools
curl -fsSLO https://nodejs.org/dist/latest-v20.x/node-v20.20.2-linux-x64.tar.xz  # pick the current file name
tar xJf node-v20.*-linux-x64.tar.xz && mv node-v20.*-linux-x64 node
export PATH="$PWD/node/bin:$PATH"
```

Then, from `frontend/`:

```bash
npm ci
npm run dev        # http://localhost:5173 — proxies /api and /healthz to http://localhost:8080
npm run typecheck  # tsc -b
npm run lint       # eslint
npm test           # vitest run
npm run build      # tsc -b && vite build -> dist/
```

Run the FastAPI backend on port 8080 (`REQUIRE_IAP=false` locally). To point the dev proxy at a
different backend: `VITE_BACKEND_URL=http://localhost:9000 npm run dev`.

## Production container

```bash
docker build -t analyst-frontend .
docker run --rm -p 8080:8080 \
  -e BACKEND_URL=https://analyst-backend-xxxxx-uc.a.run.app \
  analyst-frontend
```

Multi-stage build (`node:20-alpine` → `nginx:alpine`). The official nginx entrypoint renders
`/etc/nginx/templates/default.conf.template` with `envsubst` at startup.

| Env var        | Default                    | Purpose                                                        |
| -------------- | -------------------------- | -------------------------------------------------------------- |
| `PORT`         | `8080`                     | Listen port (Cloud Run injects it)                             |
| `BACKEND_URL`  | **required**               | Backend **origin** (no path) for `/api/` and `/healthz`        |
| `BACKEND_HOST` | host[:port] of BACKEND_URL | `Host` header sent upstream (Cloud Run routes on it)           |
| `BACKEND_SNI`  | BACKEND_HOST without port  | TLS SNI name (`proxy_ssl_server_name on`)                      |
| `DNS_RESOLVER` | first `/etc/resolv.conf` ns | nginx `resolver` so the backend host is re-resolved at runtime |

`nginx/15-backend-host.envsh` derives `BACKEND_HOST` / `BACKEND_SNI` / `DNS_RESOLVER` before the
template is rendered (the container exits if `BACKEND_URL` is missing). Because the upstream is
resolved at request time through nginx's DNS `resolver` (which ignores `/etc/hosts`), use a DNS
name or IP literal — e.g. `http://172.17.0.1:8080` for a backend on the Docker host — not
`localhost`. The proxy uses HTTP/1.1, `proxy_buffering off` (SSE), `proxy_read_timeout
300s`, and forwards `X-Goog-IAP-JWT-Assertion` / `X-Goog-Authenticated-User-Email`. Static assets
get long-lived caching; `index.html` is `no-cache`; unknown paths fall back to `index.html`.
Security headers (CSP `script-src 'self'`, `X-Frame-Options: DENY`, `nosniff`, HSTS, etc.) are in
`nginx/security-headers.conf`. Container liveness: `GET /nginx-health` (does not hit the backend).

> **Note:** nginx does not mint Google ID tokens. If the backend Cloud Run service requires IAM
> invoker auth, either allow unauthenticated ingress restricted to internal traffic and rely on
> IAP-JWT verification (`REQUIRE_IAP=true`), or front both services with the same IAP-protected
> load balancer.
