"""Observability: structured JSON logs correlated with OpenTelemetry traces (Cloud Trace)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from . import __version__
from .config import Settings

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
_configured_tracing = False


class CloudLoggingJsonFormatter(logging.Formatter):
    """Emit one JSON object per line using Cloud Logging's special fields.

    Adds ``logging.googleapis.com/trace`` / ``spanId`` from the active OTEL span so
    logs and traces are linked in the Cloud Console.
    """

    def __init__(self, project_id: str | None = None) -> None:
        super().__init__()
        self.project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
        }
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx is not None and ctx.is_valid:
            trace_id = format(ctx.trace_id, "032x")
            payload["logging.googleapis.com/trace"] = (
                f"projects/{self.project_id}/traces/{trace_id}" if self.project_id else trace_id
            )
            payload["logging.googleapis.com/spanId"] = format(ctx.span_id, "016x")
            payload["logging.googleapis.com/trace_sampled"] = bool(ctx.trace_flags.sampled)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CloudLoggingJsonFormatter(settings.google_cloud_project))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
    for noisy in ("httpx", "httpcore", "urllib3", "google_adk", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))


def configure_tracing(settings: Settings) -> None:
    """Install the global tracer provider (ADK's own agent/tool/LLM spans flow through it)."""
    global _configured_tracing
    if _configured_tracing:
        return
    provider = TracerProvider(
        resource=Resource.create({"service.name": "investment-analyst-backend", "service.version": __version__})
    )
    if settings.enable_cloud_trace:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=settings.google_cloud_project))
        )
    trace.set_tracer_provider(provider)
    _configured_tracing = True
