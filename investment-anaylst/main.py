#!/usr/bin/env python3
"""Run the Investment Analyst Agent using Google ADK.

Usage:
    # Interactive mode:
    python main.py

    # Single-query mode:
    python main.py "Research NVDA stock"
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure local folder is in python path
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Load .env file
load_dotenv(current_dir / ".env")
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from agent import root_agent


def check_api_key() -> bool:
    """Verify Google API Key is present in the environment."""
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("=" * 60)
        print("⚠️  WARNING: No GOOGLE_API_KEY or GEMINI_API_KEY found.")
        print("To query Gemini, please set your API key in one of two ways:")
        print(f"  1. Add it to {current_dir / '.env'}:")
        print("     GOOGLE_API_KEY=your_gemini_api_key_here")
        print("  2. Or export it in your shell:")
        print("     export GOOGLE_API_KEY='your_gemini_api_key_here'")
        print("=" * 60)
        return False
    # Ensure GOOGLE_API_KEY is set for google-genai
    if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    return True


async def run_query(runner: Runner, session_service: InMemorySessionService, session_id: str, query: str):
    """Execute a single turn query against the investment analyst agent."""
    print(f"\n📈 [User]: {query}\n")
    new_message = types.Content(role="user", parts=[types.Part(text=query)])
    
    async for event in runner.run_async(
        user_id="analyst_user",
        session_id=session_id,
        new_message=new_message,
    ):
        # Display tool calls if any
        if hasattr(event, "get_function_calls"):
            calls = event.get_function_calls()
            for call in calls:
                print(f"⚙️  [Tool Call]: {call.name}({dict(call.args or {})})")

        # Stream or display response text
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text, end="", flush=True)
    print("\n")


async def main():
    print("=" * 60)
    print("📊 Google ADK Investment Analyst Agent")
    print("=" * 60)

    has_key = check_api_key()
    if not has_key:
        sys.exit(1)

    # Initialize in-memory session service and ADK runner
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="investment_analyst",
        user_id="analyst_user",
    )
    runner = Runner(
        agent=root_agent,
        app_name="investment_analyst",
        session_service=session_service,
    )

    # If query provided as command line arguments
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        await run_query(runner, session_service, session.id, query)
        return

    # Interactive REPL mode
    print("Enter a stock ticker or research prompt (type 'exit' or 'quit' to stop):")
    print("Example: 'Analyze Tesla and give me a bull/bear breakdown'\n")

    while True:
        try:
            user_input = input("investment-analyst> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            await run_query(runner, session_service, session.id, user_input)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break


if __name__ == "__main__":
    asyncio.run(main())
