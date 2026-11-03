"""SSE relay: keep-alive comments during slow agent work, error framing, cancellation."""

from __future__ import annotations

import asyncio

from analyst.api.app import sse_with_heartbeat
from analyst.api.schemas import ChatRequest
from analyst.services.analyst_service import StreamEvent, UserIdentity

USER = UserIdentity(user_id="u", email="u@example.com")
BODY = ChatRequest(message="hi")


class SlowService:
    def __init__(self, delay: float, fail: bool = False):
        self.delay = delay
        self.fail = fail
        self.cancelled = False

    async def stream(self, body, user):
        yield StreamEvent("session", {"session_id": "s"})
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.fail:
            raise RuntimeError("boom")
        yield StreamEvent("final", {"ok": True})


async def _collect(gen):
    return [chunk async for chunk in gen]


async def test_heartbeat_emitted_while_idle():
    chunks = await _collect(sse_with_heartbeat(SlowService(0.12), BODY, USER, heartbeat_seconds=0.03))
    assert chunks[0].startswith(b"event: session")
    assert chunks[-1].startswith(b"event: final")
    assert b": keepalive\n\n" in chunks


async def test_no_heartbeat_when_fast():
    chunks = await _collect(sse_with_heartbeat(SlowService(0), BODY, USER, heartbeat_seconds=5))
    assert b": keepalive\n\n" not in chunks
    assert len(chunks) == 2


async def test_errors_are_framed_as_sse():
    chunks = await _collect(sse_with_heartbeat(SlowService(0, fail=True), BODY, USER, heartbeat_seconds=5))
    assert chunks[-1].startswith(b"event: error")
    assert b"internal_error" in chunks[-1]


async def test_client_disconnect_cancels_producer():
    svc = SlowService(10)
    gen = sse_with_heartbeat(svc, BODY, USER, heartbeat_seconds=5)
    first = await gen.__anext__()
    assert first.startswith(b"event: session")
    await gen.aclose()
    await asyncio.sleep(0.01)
    assert svc.cancelled is True
