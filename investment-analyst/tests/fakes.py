"""Scripted fake LLM for exercising the real ADK agent tree without calling Gemini."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class Call:
    """A scripted function call step (one or more parallel calls)."""

    def __init__(self, *calls: tuple[str, dict[str, Any]]):
        self.calls = calls


Step = Call | str | Callable[[LlmRequest], "Call | str"]


class ScriptedLlm(BaseLlm):
    """Returns pre-scripted responses in order; the last step repeats if exhausted."""

    script: list[Any] = []
    requests: list[Any] = []
    stream_words: bool = True

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        step = self.script[min(len(self.requests) - 1, len(self.script) - 1)]
        if callable(step) and not isinstance(step, Call):
            step = step(llm_request)
        usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=20, total_token_count=120
        )
        if isinstance(step, Call):
            parts = [types.Part.from_function_call(name=name, args=args) for name, args in step.calls]
            yield LlmResponse(content=types.Content(role="model", parts=parts), usage_metadata=usage)
            return
        if stream and self.stream_words:
            words = step.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield LlmResponse(
                    content=types.Content(role="model", parts=[types.Part.from_text(text=chunk)]), partial=True
                )
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part.from_text(text=step)]), usage_metadata=usage
        )


def system_text(llm_request: LlmRequest) -> str:
    return str(llm_request.config.system_instruction or "")
