import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import bigquery
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aegis-gateway")

app = FastAPI(title="Project Aegis Enterprise AI Gateway", version="1.0.0")

PROJECT_ID = os.environ.get("PROJECT_ID", "aegis-testing-508614")
GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET", "aegis_telemetry")
VERTEX_ENDPOINT = f"https://{GCP_REGION}-aiplatform.googleapis.com"

# Google Auth credentials for Vertex AI egress
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
auth_req = GoogleAuthRequest()

# BigQuery client
bq_client = None
try:
    bq_client = bigquery.Client(project=PROJECT_ID)
except Exception as e:
    logger.warning(f"Could not initialize BigQuery client: {e}")

# Async HTTP client
http_client = httpx.AsyncClient(timeout=120.0)


def get_vertex_token() -> str:
    """Refreshes and returns a valid Google OAuth2 access token for Vertex AI."""
    if not creds.valid:
        creds.refresh(auth_req)
    return creds.token


def log_telemetry(
    session_id: str,
    client_type: str,
    path: str,
    model: str,
    status_code: int,
    latency_ms: float,
    prompt_preview: str,
    tokens: Dict[str, Any],
):
    """Asynchronously logs request telemetry to BigQuery."""
    if not bq_client:
        return
    try:
        table_id = f"{PROJECT_ID}.{BIGQUERY_DATASET}.routing_logs"
        rows = [
            {
                "session_id": session_id or "anonymous",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "client_type": client_type,
                "endpoint_path": path,
                "model": model,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "prompt_preview": prompt_preview[:500] if prompt_preview else "",
                "prompt_tokens": tokens.get("prompt_token_count", 0),
                "candidates_tokens": tokens.get("candidates_token_count", 0),
                "total_tokens": tokens.get("total_token_count", 0),
            }
        ]
        errors = bq_client.insert_rows_json(table_id, rows)
        if errors:
            logger.warning(f"BigQuery insert errors: {errors}")
        else:
            logger.info(f"[TELEMETRY] Logged session {session_id} to BigQuery ({latency_ms:.1f}ms, status={status_code})")
    except Exception as e:
        logger.warning(f"Telemetry logging error: {e}")


@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting Project Aegis Gateway for project: {PROJECT_ID}, region: {GCP_REGION}")
    # Ensure BigQuery table exists
    if bq_client:
        table_id = f"{PROJECT_ID}.{BIGQUERY_DATASET}.routing_logs"
        schema = [
            bigquery.SchemaField("session_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("client_type", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("endpoint_path", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("model", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("status_code", "INTEGER", mode="NULLABLE"),
            bigquery.SchemaField("latency_ms", "FLOAT", mode="NULLABLE"),
            bigquery.SchemaField("prompt_preview", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("prompt_tokens", "INTEGER", mode="NULLABLE"),
            bigquery.SchemaField("candidates_tokens", "INTEGER", mode="NULLABLE"),
            bigquery.SchemaField("total_tokens", "INTEGER", mode="NULLABLE"),
        ]
        try:
            table = bigquery.Table(table_id, schema=schema)
            bq_client.create_table(table, exists_ok=True)
            logger.info(f"BigQuery telemetry table verified: {table_id}")
        except Exception as e:
            logger.warning(f"Failed to create BigQuery table: {e}")


@app.get("/")
@app.get("/health")
@app.get("/healthz")
async def health():
    return {
        "status": "HEALTHY",
        "service": "Project Aegis Enterprise AI Gateway",
        "region": GCP_REGION,
        "project": PROJECT_ID,
        "egress": "Direct VPC Egress (corp-workload-subnet)",
    }


# ==============================================================================
# Google GenAI SDK Proxy Endpoint & OpenAI Support
# ==============================================================================
@app.post("/v1beta1/{path:path}")
@app.post("/v1/{path:path}")
@app.post("/v1beta/{path:path}")
async def proxy_genai(request: Request, path: str):
    if path == "chat/completions":
        return await openai_chat_completions(request)
    start_time = time.time()
    session_id = request.headers.get("x-aegis-session-id", "default_session")
    raw_body = await request.body()
    body_json = {}
    try:
        body_json = json.loads(raw_body)
    except Exception:
        pass

    # Extract model name from URL or body
    model_name = "unknown"
    if "models/" in path:
        model_part = path.split("models/")[1]
        model_name = model_part.split(":")[0]

    # Target URL on Vertex AI (dynamic multi-region & global support)
    request_path = request.url.path
    query_str = str(request.url.query)

    req_location = GCP_REGION
    if "/locations/" in request_path:
        req_location = request_path.split("/locations/")[1].split("/")[0]

    if req_location == "global":
        upstream_host = "aiplatform.googleapis.com"
        target_url = f"https://aiplatform.googleapis.com{request_path}"
    else:
        upstream_host = f"{req_location}-aiplatform.googleapis.com"
        target_url = f"https://{req_location}-aiplatform.googleapis.com{request_path}"

    if query_str:
        target_url += f"?{query_str}"

    token = get_vertex_token()
    forward_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Host": upstream_host,
    }

    logger.info(f"[AEGIS GENAI] Session: {session_id} -> Forwarding to Vertex AI ({req_location}): {target_url}")

    try:
        vertex_resp = await http_client.post(
            target_url,
            content=raw_body,
            headers=forward_headers,
        )
        latency_ms = (time.time() - start_time) * 1000

        resp_content = vertex_resp.content
        resp_json = {}
        try:
            resp_json = vertex_resp.json()
        except Exception:
            pass

        tokens = resp_json.get("usageMetadata", {})

        # Preview prompt text
        prompt_text = ""
        contents = body_json.get("contents", [])
        if contents and isinstance(contents, list):
            for c in contents:
                for part in c.get("parts", []):
                    if "text" in part:
                        prompt_text += part["text"] + " "

        # Record telemetry in background
        asyncio.create_task(
            asyncio.to_thread(
                log_telemetry,
                session_id=session_id,
                client_type="google-genai",
                path=request_path,
                model=model_name,
                status_code=vertex_resp.status_code,
                latency_ms=latency_ms,
                prompt_preview=prompt_text.strip(),
                tokens=tokens,
            )
        )

        return Response(
            content=resp_content,
            status_code=vertex_resp.status_code,
            media_type=vertex_resp.headers.get("content-type", "application/json"),
        )
    except Exception as e:
        logger.error(f"[AEGIS GENAI ERROR] {e}")
        raise HTTPException(status_code=502, detail=f"Aegis Gateway upstream error: {str(e)}")


# ==============================================================================
# OpenAI SDK Proxy Endpoint
# ==============================================================================
@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    start_time = time.time()
    session_id = request.headers.get("x-aegis-session-id", "default_session")
    body = await request.json()
    model = body.get("model", "gemini-2.5-flash")
    messages = body.get("messages", [])

    logger.info(f"[AEGIS OPENAI] Session: {session_id} -> Translating OpenAI request for model: {model}")

    # Build Gemini prompt parts from messages
    gemini_contents = []
    system_instruction = None
    prompt_text = ""

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            system_instruction = {"parts": [{"text": content}]}
        elif role == "assistant":
            gemini_contents.append({"role": "model", "parts": [{"text": content}]})
        else:
            gemini_contents.append({"role": "user", "parts": [{"text": content}]})
            prompt_text += content + " "

    gemini_payload = {"contents": gemini_contents}
    if system_instruction:
        gemini_payload["systemInstruction"] = system_instruction

    if "temperature" in body:
        gemini_payload.setdefault("generationConfig", {})["temperature"] = body["temperature"]
    if "max_tokens" in body:
        gemini_payload.setdefault("generationConfig", {})["maxOutputTokens"] = body["max_tokens"]

    # Target Vertex AI endpoint (dynamic multi-region & global support)
    req_location = body.get("location", GCP_REGION)
    if req_location == "global":
        upstream_host = "aiplatform.googleapis.com"
        target_url = (
            f"https://aiplatform.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/global/"
            f"publishers/google/models/{model}:generateContent"
        )
    else:
        upstream_host = f"{req_location}-aiplatform.googleapis.com"
        target_url = (
            f"https://{req_location}-aiplatform.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/{req_location}/"
            f"publishers/google/models/{model}:generateContent"
        )

    token = get_vertex_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Host": upstream_host,
    }

    try:
        resp = await http_client.post(target_url, json=gemini_payload, headers=headers)
        latency_ms = (time.time() - start_time) * 1000

        if resp.status_code != 200:
            return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

        gemini_resp = resp.json()
        candidate = gemini_resp.get("candidates", [{}])[0]
        content_obj = candidate.get("content", {})
        parts = content_obj.get("parts", [{}])
        text_content = "".join([p.get("text", "") for p in parts])

        usage_meta = gemini_resp.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)
        total_tokens = usage_meta.get("totalTokenCount", 0)

        # Build standard OpenAI chat completion response
        openai_resp = {
            "id": f"chatcmpl-aegis-{int(time.time()*1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text_content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "system_fingerprint": f"aegis-{GCP_REGION}-v1",
        }

        # Log telemetry in background
        asyncio.create_task(
            asyncio.to_thread(
                log_telemetry,
                session_id=session_id,
                client_type="openai-sdk",
                path="/v1/chat/completions",
                model=model,
                status_code=200,
                latency_ms=latency_ms,
                prompt_preview=prompt_text.strip(),
                tokens={
                    "prompt_token_count": prompt_tokens,
                    "candidates_token_count": completion_tokens,
                    "total_token_count": total_tokens,
                },
            )
        )

        return JSONResponse(content=openai_resp)
    except Exception as e:
        logger.error(f"[AEGIS OPENAI ERROR] {e}")
        raise HTTPException(status_code=502, detail=f"Aegis Gateway error: {str(e)}")


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "gemini-2.5-flash", "object": "model", "owned_by": "google"},
            {"id": "gemini-2.5-pro", "object": "model", "owned_by": "google"},
            {"id": "gemini-1.5-flash", "object": "model", "owned_by": "google"},
        ],
    }
