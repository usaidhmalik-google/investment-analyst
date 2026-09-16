#!/usr/bin/env python3
"""Main Entrypoint for the Investment Analyst Agent.

Supports interactive CLI usage, single-query runs, file-based prompt execution,
and automated benchmarking with optional Project Aegis Gateway cutover.

Usage:
    # Run through Project Aegis Gateway (default):
    python main.py "Research NVDA stock"

    # Run through direct Vertex AI baseline (bypass Aegis):
    python main.py "Research NVDA stock" --direct

    # Run with a prompt file and output JSON for test harnesses:
    python main.py --prompt-file prompts/bench01_nvda.txt --json

    # Interactive mode:
    python main.py
"""

import argparse
import json
import os
import sys
from pathlib import Path


# Ensure investment-analyst package directory is in sys.path
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Load local .env if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv(current_dir / ".env")
    load_dotenv()
except ImportError:
    pass

from agent import (
    DEFAULT_AEGIS_URL,
    DEFAULT_LOCATION,
    DEFAULT_MODEL,
    DEFAULT_SESSION_ID,
    InvestmentAnalystAgent,
    get_network_context,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Investment Analyst Agent CLI (Vertex AI / Project Aegis Gateway)"
    )
    parser.add_argument(
        "query",
        nargs="*",
        default=[],
        help="Query or stock research request",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Explicit prompt string",
    )
    parser.add_argument(
        "--prompt-file",
        type=str,
        default=None,
        help="Path to file containing prompt text",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        default=False,
        help="Bypass Project Aegis AI Gateway (Direct Vertex AI baseline)",
    )
    parser.add_argument(
        "--aegis-url",
        type=str,
        default=DEFAULT_AEGIS_URL,
        help="Project Aegis Cloud Run Gateway URL",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=DEFAULT_SESSION_ID,
        help="Session ID for Aegis telemetry tracking",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help="Gemini model name (default: gemini-2.5-flash)",
    )
    parser.add_argument(
        "--location",
        type=str,
        default=os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION),
        help="GCP region for Vertex AI (default: global)",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=os.environ.get("GOOGLE_CLOUD_PROJECT", None),
        help="GCP project ID",
    )
    parser.add_argument(
        "--thinking-budget",
        type=int,
        default=1024,
        help="Thinking budget token count (default: 1024)",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=4096,
        help="Max output tokens (default: 4096)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON payload for automated test runners",
    )
    return parser.parse_args()


def run_interactive(agent: InvestmentAnalystAgent):
    """Run an interactive CLI chat session with the analyst."""
    print("=" * 70)
    print("  📈 Investment Analyst Agent (Interactive Console)")
    print(f"  Routing: {'Direct Vertex AI' if agent.direct else f'Project Aegis Gateway ({agent.aegis_url})'}")
    print(f"  Model:   {agent.model}")
    print("  Type 'quit' or 'exit' to exit.")
    print("=" * 70)

    turn = 0
    while True:
        try:
            prompt = input("\n[Analyst User] > ").strip()
            if not prompt:
                continue
            if prompt.lower() in ("quit", "exit", "q"):
                print("\nGoodbye!")
                break

            turn += 1
            session_id = f"{agent.session_id}_turn_{turn}"
            result = agent.run(prompt, session_id=session_id)

            print("\n[AI Analyst]:")
            print(result["response"])
            if result.get("tools_called"):
                tools_str = ", ".join(t["tool"] for t in result["tools_called"])
                print(f"\n[Tools Executed: {tools_str}]")
            print(f"[Latency: {result['latency_seconds']}s | Tokens: {result['usage'].get('total_tokens')}]")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break


def main():
    args = parse_args()

    # Determine prompt text
    prompt = None
    if args.prompt_file:
        p_path = Path(args.prompt_file)
        if not p_path.exists():
            print(f"Error: Prompt file '{args.prompt_file}' not found.", file=sys.stderr)
            sys.exit(1)
        prompt = p_path.read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    elif args.query:
        prompt = " ".join(args.query)

    # Initialize agent
    agent = InvestmentAnalystAgent(
        aegis_url=args.aegis_url,
        session_id=args.session_id,
        direct=args.direct,
        model=args.model,
        location=args.location,
        project=args.project,
        thinking_budget=args.thinking_budget,
        max_output_tokens=args.max_output_tokens,
    )

    # Interactive mode if no prompt provided
    if not prompt:
        run_interactive(agent)
        return

    # Single-turn execution
    net_ctx = agent.network_context
    if not args.json:
        print("=" * 75)
        if args.direct:
            print("CUSTOMER AGENT: Direct Vertex AI Baseline")
            endpoint_str = f"https://{args.location}-aiplatform.googleapis.com"
        else:
            print("CUSTOMER AGENT: Project Aegis Enterprise AI Gateway")
            endpoint_str = args.aegis_url
        print("=" * 75)
        print(f"[*] Workload IP:         {net_ctx['primary_ip']}")
        print(f"[*] Subnet Verification: {'[VERIFIED 10.10.0.0/20]' if net_ctx['is_private_subnet'] else '[External]'}")
        print(f"[*] Target Endpoint:     {endpoint_str}")
        if not args.direct:
            print(f"[*] Session ID Header:   X-Aegis-Session-ID = {args.session_id}")
        print(f"[*] Model:               {args.model}")
        print("-" * 75)

    result = agent.run(prompt, session_id=args.session_id)

    if args.json:
        print("__JSON_PAYLOAD_START__")
        print(json.dumps(result, indent=2))
        print("__JSON_PAYLOAD_END__")
    else:
        print("-" * 75)
        print(f"[+] Response Received in {result['latency_seconds']}s:")
        print(result["response"].strip())
        print("-" * 75)
        if result.get("tools_called"):
            tools_list = [t["tool"] for t in result["tools_called"]]
            print(f"[*] Tools Executed:      {len(tools_list)} calls: {tools_list}")
        u = result.get("usage", {})
        print(f"[*] Token Usage:         Prompt: {u.get('prompt_tokens')}, Candidates: {u.get('candidates_tokens')}, Total: {u.get('total_tokens')}")
        print("=" * 75)


if __name__ == "__main__":
    main()
