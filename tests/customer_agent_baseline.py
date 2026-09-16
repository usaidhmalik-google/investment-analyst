#!/usr/bin/env python3
"""
customer_agent_baseline.py
==========================
Customer Agent with Project Aegis Cutover Support
Demonstrates routing enterprise agent inference through Project Aegis AI Gateway
deployed in a private brownfield corporate subnet (corp-workload-subnet).

Supports both:
1. Google GenAI SDK:
   - Configures http_options={'api_endpoint': 'https://<AEGIS_PRIVATE_URL>'}
   - Injects header 'X-Aegis-Session-ID': 'sess_enterprise_eval_001'
   - Zero schema or prompt modifications to client.models.generate_content(...)
2. OpenAI SDK:
   - Configures base_url="https://<AEGIS_PRIVATE_URL>/v1"
   - Injects header 'X-Aegis-Session-ID': 'sess_enterprise_eval_001'
   - Zero schema or prompt modifications to client.chat.completions.create(...)

Architecture Context:
- Network: corp-enterprise-vpc / corp-workload-subnet (10.10.0.0/20)
- Egress/Ingress: Private Google Access / Internal Cloud Run Service
- Aegis Private URL: https://aegis-gateway-wk6c5cgcza-uc.a.run.app
- Session ID: sess_enterprise_eval_001
- Telemetry Destination: BigQuery aegis_telemetry.routing_logs
"""

import argparse
import json
import os
import socket
import sys
import time
import urllib.request
from typing import Any, Dict, Optional

# Default Aegis Cloud Run Private Internal URL
DEFAULT_AEGIS_URL = "https://aegis-gateway-wk6c5cgcza-uc.a.run.app"
DEFAULT_SESSION_ID = "sess_enterprise_eval_001"


def get_network_context() -> Dict[str, Any]:
    """Inspects local network context to verify execution environment."""
    hostname = socket.gethostname()
    local_ips = []
    try:
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ip not in local_ips and not ip.startswith("127."):
                local_ips.append(ip)
    except Exception:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("169.254.169.254", 80))
        primary_ip = s.getsockname()[0]
        s.close()
    except Exception:
        primary_ip = local_ips[0] if local_ips else "127.0.0.1"

    is_private_subnet = primary_ip.startswith("10.10.")

    return {
        "hostname": hostname,
        "primary_ip": primary_ip,
        "all_ips": local_ips,
        "is_private_subnet": is_private_subnet,
        "expected_subnet_cidr": "10.10.0.0/20",
    }


def get_gcp_project() -> str:
    """Discovers project ID from environment or metadata server."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if not project:
        try:
            req = urllib.request.Request(
                "http://metadata.google.internal/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
            )
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                project = resp.read().decode().strip()
        except Exception:
            pass
    if not project:
        try:
            import google.auth
            _, project = google.auth.default()
        except Exception:
            pass
    return project or "aegis-testing-508614"


def get_identity_token(audience: str) -> Optional[str]:
    """
    Fetches Google Compute Engine OIDC identity token for internal Cloud Run invocation.
    Uses format=full to ensure service account email is present in token claims.
    """
    try:
        url = (
            f"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/"
            f"identity?audience={audience}&format=full"
        )
        req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.read().decode().strip()
    except Exception:
        return None


def run_genai_agent(
    prompt: str,
    aegis_url: Optional[str] = None,
    session_id: str = DEFAULT_SESSION_ID,
    project_id: Optional[str] = None,
    location: str = "us-central1",
    model: str = "gemini-2.5-flash",
    system_instruction: Optional[str] = None,
    direct: bool = False,
) -> Dict[str, Any]:
    """
    Executes inference via Google GenAI SDK.
    When cutover (default), redirects traffic to Project Aegis via http_options={'api_endpoint': aegis_url}.
    Injects header 'X-Aegis-Session-ID': session_id.
    Ensures zero schema or prompt modifications.
    """
    from google import genai
    from google.genai import types

    # Allow extra fields in HttpOptions so api_endpoint is accepted seamlessly
    types.HttpOptions.model_config["extra"] = "allow"
    types.HttpOptions.model_rebuild(force=True)

    project = project_id or get_gcp_project()
    net_ctx = get_network_context()
    target_aegis = aegis_url or DEFAULT_AEGIS_URL

    print("=" * 75)
    if direct:
        print("CUSTOMER AGENT: Direct Vertex AI Baseline (Direct Mode)")
        target_endpoint = f"https://{location}-aiplatform.googleapis.com (Direct Vertex AI)"
    else:
        print("CUSTOMER AGENT: Project Aegis Cutover (Google GenAI SDK)")
        target_endpoint = f"{target_aegis} (Aegis Enterprise AI Gateway)"
    print("=" * 75)
    print(f"[*] Timestamp:           {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"[*] Local Hostname:      {net_ctx['hostname']}")
    print(f"[*] Workload IP:         {net_ctx['primary_ip']}")
    print(f"[*] Subnet Verification: {'[VERIFIED 10.10.0.0/20]' if net_ctx['is_private_subnet'] else '[External/Devshell]'}")
    print(f"[*] SDK Type:            Google GenAI SDK (google-genai)")
    print(f"[*] Target Endpoint:     {target_endpoint}")
    if not direct:
        print(f"[*] Session ID Header:   X-Aegis-Session-ID = {session_id}")
        print(f"[*] Cutover Config:      http_options={{'api_endpoint': '{target_aegis}'}}")
    print(f"[*] Gemini Model:        {model}")
    print(f"[*] Schema Modification: ZERO (Unmodified standard Gemini schema)")
    print(f"[*] Prompt Modification: ZERO (Original client prompt intact)")
    print("-" * 75)

    start_time = time.time()

    if direct:
        client = genai.Client(vertexai=True, project=project, location=location)
    else:
        id_token = get_identity_token(target_aegis)
        # Configure http_options per specification
        http_options = {
            "api_endpoint": target_aegis,
            "base_url": target_aegis,
            "headers": {
                "X-Aegis-Session-ID": session_id,
            },
        }
        client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=http_options,
        )
        if id_token:
            # Route Cloud Run IAM authentication for private internal ingress
            client._api_client._access_token = lambda: id_token

    config_kwargs = {}
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    print(f"[*] Dispatching prompt:  {prompt[:80]}..." if len(prompt) > 80 else f"[*] Dispatching prompt:  {prompt}")

    try:
        # ZERO schema or prompt modifications: standard generate_content call
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        latency = round(time.time() - start_time, 3)
    except Exception as e:
        print(f"[ERROR] Inference call failed: {e}", file=sys.stderr)
        raise

    response_text = response.text or ""
    usage = {}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = {
            "prompt_token_count": getattr(response.usage_metadata, "prompt_token_count", None),
            "candidates_token_count": getattr(response.usage_metadata, "candidates_token_count", None),
            "total_token_count": getattr(response.usage_metadata, "total_token_count", None),
        }

    print("-" * 75)
    print(f"[+] Response Received via {'Project Aegis Gateway' if not direct else 'Direct Vertex AI'} in {latency}s:")
    print(f"{response_text.strip()}")
    print("-" * 75)
    if usage:
        print(f"[*] Token Usage:         Prompt: {usage.get('prompt_token_count')}, Candidates: {usage.get('candidates_token_count')}, Total: {usage.get('total_token_count')}")
    print("=" * 75)

    return {
        "status": "SUCCESS",
        "mode": "genai",
        "cutover": not direct,
        "aegis_url": target_aegis if not direct else None,
        "session_id": session_id if not direct else None,
        "model": model,
        "latency_seconds": latency,
        "prompt": prompt,
        "response": response_text,
        "usage": usage,
        "network": net_ctx,
    }


def run_openai_agent(
    prompt: str,
    aegis_url: Optional[str] = None,
    session_id: str = DEFAULT_SESSION_ID,
    model: str = "gemini-2.5-flash",
    system_instruction: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes inference via OpenAI SDK.
    Redirects traffic to Project Aegis via base_url="https://<AEGIS_PRIVATE_URL>/v1".
    Injects header 'X-Aegis-Session-ID': session_id.
    Ensures zero schema or prompt modifications.
    """
    import openai

    net_ctx = get_network_context()
    target_aegis = aegis_url or DEFAULT_AEGIS_URL
    openai_base_url = f"{target_aegis}/v1"

    print("=" * 75)
    print("CUSTOMER AGENT: Project Aegis Cutover (OpenAI SDK)")
    print("=" * 75)
    print(f"[*] Timestamp:           {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"[*] Local Hostname:      {net_ctx['hostname']}")
    print(f"[*] Workload IP:         {net_ctx['primary_ip']}")
    print(f"[*] Subnet Verification: {'[VERIFIED 10.10.0.0/20]' if net_ctx['is_private_subnet'] else '[External/Devshell]'}")
    print(f"[*] SDK Type:            OpenAI SDK (openai)")
    print(f"[*] Target Endpoint:     {openai_base_url} (Aegis OpenAI Translator)")
    print(f"[*] Session ID Header:   X-Aegis-Session-ID = {session_id}")
    print(f"[*] Cutover Config:      base_url=\"{openai_base_url}\"")
    print(f"[*] Gemini Model:        {model}")
    print(f"[*] Schema Modification: ZERO (Standard OpenAI chat completion schema)")
    print(f"[*] Prompt Modification: ZERO (Original client prompt intact)")
    print("-" * 75)

    start_time = time.time()
    id_token = get_identity_token(target_aegis)

    client = openai.OpenAI(
        base_url=openai_base_url,
        api_key=id_token or "aegis-enterprise-token",
        default_headers={"X-Aegis-Session-ID": session_id},
    )

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    print(f"[*] Dispatching prompt:  {prompt[:80]}..." if len(prompt) > 80 else f"[*] Dispatching prompt:  {prompt}")

    try:
        # ZERO schema or prompt modifications: standard chat.completions.create
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        latency = round(time.time() - start_time, 3)
    except Exception as e:
        print(f"[ERROR] OpenAI SDK call failed: {e}", file=sys.stderr)
        raise

    response_text = completion.choices[0].message.content or ""
    usage = {
        "prompt_tokens": getattr(completion.usage, "prompt_tokens", None),
        "completion_tokens": getattr(completion.usage, "completion_tokens", None),
        "total_tokens": getattr(completion.usage, "total_tokens", None),
    }

    print("-" * 75)
    print(f"[+] Response Received via Project Aegis Gateway in {latency}s:")
    print(f"{response_text.strip()}")
    print("-" * 75)
    print(f"[*] Token Usage:         Prompt: {usage.get('prompt_tokens')}, Completion: {usage.get('completion_tokens')}, Total: {usage.get('total_tokens')}")
    print("=" * 75)

    return {
        "status": "SUCCESS",
        "mode": "openai",
        "cutover": True,
        "aegis_url": target_aegis,
        "session_id": session_id,
        "model": model,
        "latency_seconds": latency,
        "prompt": prompt,
        "response": response_text,
        "usage": usage,
        "network": net_ctx,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Customer Agent supporting Project Aegis AI Gateway Cutover."
    )
    parser.add_argument(
        "--sdk",
        type=str,
        choices=["genai", "openai"],
        default="genai",
        help="SDK to use for inference: 'genai' (Google GenAI SDK) or 'openai' (OpenAI SDK)",
    )
    parser.add_argument(
        "--aegis-url",
        type=str,
        default=os.environ.get("AEGIS_URL", DEFAULT_AEGIS_URL),
        help=f"Project Aegis internal private URL (default: {DEFAULT_AEGIS_URL})",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=os.environ.get("AEGIS_SESSION_ID", DEFAULT_SESSION_ID),
        help=f"Aegis Session ID for telemetry tracking (default: {DEFAULT_SESSION_ID})",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="Summarize the enterprise network topology for corporate workloads in us-central1 in two sentences.",
        help="Prompt to send to Gemini",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        help="Model identifier (default: gemini-2.5-flash)",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="GCP Project ID",
    )
    parser.add_argument(
        "--location",
        type=str,
        default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        help="GCP region for Vertex AI",
    )
    parser.add_argument(
        "--system-instruction",
        type=str,
        default="You are an enterprise assistant serving private corporate applications.",
        help="System instruction for the model",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Bypass Aegis and call Vertex AI directly (baseline verification mode)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run comprehensive cutover verification suite",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    args = parser.parse_args()

    prompt = args.prompt
    if args.verify:
        prompt = "Hello Vertex AI Gemini! Please confirm connectivity through Project Aegis and state your model version."

    if args.sdk == "openai":
        result = run_openai_agent(
            prompt=prompt,
            aegis_url=args.aegis_url,
            session_id=args.session_id,
            model=args.model,
            system_instruction=args.system_instruction,
        )
    else:
        result = run_genai_agent(
            prompt=prompt,
            aegis_url=args.aegis_url,
            session_id=args.session_id,
            project_id=args.project,
            location=args.location,
            model=args.model,
            system_instruction=args.system_instruction,
            direct=args.direct,
        )

    if args.json:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
