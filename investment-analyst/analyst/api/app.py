"""FastAPI application: chat (JSON + SSE streaming), feedback, config and health endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .. import __version__
from ..config import STRATEGIES, Settings, get_settings
from ..services.analyst_service import AnalystService, UserIdentity
from ..services.report_store import ReportNotFoundError, build_report_store
from ..services.telemetry_sink import TelemetrySink
from ..telemetry import configure_logging, configure_tracing
from .auth import resolve_user
from .schemas import ChatRequest, ChatResponse, ConfigResponse, FeedbackRequest

logger = logging.getLogger(__name__)


def _sse(event_type: str, data: dict) -> bytes:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n".encode()


async def sse_with_heartbeat(
    svc: AnalystService, body: ChatRequest, user: UserIdentity, heartbeat_seconds: float
) -> AsyncIterator[bytes]:
    """Relay service events as SSE, emitting ``: keepalive`` comments while agents/tools are busy.

    Keeps idle proxies and load balancers from closing the stream during long tool calls
    (e.g. downloading a 10-K). The producer is cancelled if the client disconnects.
    """
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in svc.stream(body, user):
                await queue.put(_sse(event.type, event.data))
        except Exception:
            logger.exception("stream failed")
            await queue.put(_sse("error", {"code": "internal_error", "message": "Unexpected server error."}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                yield b": keepalive\n\n"
                continue
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()


def get_service(request: Request) -> AnalystService:
    return request.app.state.service


def get_user(request: Request) -> UserIdentity:
    return resolve_user(request, request.app.state.settings)


ServiceDep = Annotated[AnalystService, Depends(get_service)]
UserDep = Annotated[UserIdentity, Depends(get_user)]


def create_app(settings: Settings | None = None, service: AnalystService | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings)
        configure_tracing(settings)
        if service is None:
            app.state.service = AnalystService(
                settings=settings, store=build_report_store(settings), telemetry=TelemetrySink(settings)
            )
        else:
            app.state.service = service
        logger.info(
            "investment analyst backend started",
            extra={
                "version": __version__,
                "router_model": settings.router_model,
                "reasoning_model": settings.reasoning_model,
                "offline_mode": settings.offline_mode,
                "prompt_version": settings.prompt_version,
            },
        )
        yield
        await app.state.service.telemetry.drain()

    app = FastAPI(title="Investment Analyst Agent", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
    except Exception:  # noqa: BLE001  # pragma: no cover - instrumentation is optional
        logger.warning("FastAPI OpenTelemetry instrumentation unavailable")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config", response_model=ConfigResponse)
    async def config(_: UserDep) -> ConfigResponse:
        return ConfigResponse(
            strategies=list(STRATEGIES),
            models={"router": settings.router_model, "reasoning": settings.reasoning_model},
            offline_mode=settings.offline_mode,
            prompt_version=settings.prompt_version,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, svc: ServiceDep, user: UserDep) -> ChatResponse:
        try:
            return await svc.run(body, user)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/chat/stream")
    async def chat_stream(body: ChatRequest, svc: ServiceDep, user: UserDep) -> StreamingResponse:
        return StreamingResponse(
            sse_with_heartbeat(svc, body, user, settings.sse_heartbeat_seconds),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.post("/api/feedback")
    async def feedback(body: FeedbackRequest, svc: ServiceDep, user: UserDep) -> dict[str, str]:
        label = user.email or user.user_id
        try:
            await svc.store.add_feedback(body.report_id, label, body.rating, body.comment)
        except ReportNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Unknown report_id") from exc
        svc.telemetry.record_audit(
            user=label, action=f"feedback_{body.rating}", tickers=[], session_id=None,
            report_id=body.report_id, status="ok",
        )  # fmt: skip
        return {"status": "ok"}

    return app
