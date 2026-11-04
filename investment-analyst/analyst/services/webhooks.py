"""Event-driven extension points: in-process event bus and HMAC-signed outbound webhooks.

Satisfies Designing for Change -> Extensibility by allowing downstream systems
(Slack/Teams alert bots, compliance archival pipelines, portfolio OMS monitors, or
Pub/Sub bridges) to subscribe to ``report.completed``, ``guardrail.blocked``, and
``feedback.received`` events without modifying core orchestrator or API code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..data import http

logger = logging.getLogger(__name__)

WebhookSubscriber = Callable[["WebhookEvent"], None]


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    event_type: str
    timestamp: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


def sign_webhook_payload(secret: str, timestamp: str, body_bytes: bytes) -> str:
    """Return ``sha256=<hex>`` HMAC-SHA256 signature over ``<timestamp>.<body>``."""
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("utf-8"))
    mac.update(b".")
    mac.update(body_bytes)
    return f"sha256={mac.hexdigest()}"


def verify_webhook_signature(secret: str, timestamp: str, body_bytes: bytes, signature_header: str) -> bool:
    """Constant-time verification of an ``X-Analyst-Signature`` header."""
    expected = sign_webhook_payload(secret, timestamp, body_bytes)
    return hmac.compare_digest(expected, signature_header or "")


class WebhookDispatcher:
    """Dispatches lifecycle events to in-process subscribers and optional HTTP webhook endpoints."""

    def __init__(self, target_url: str = "", secret: str = "") -> None:
        self.target_url = (target_url or "").strip()
        self.secret = secret or ""
        self._subscribers: dict[str, list[WebhookSubscriber]] = defaultdict(list)
        self.recent_events: list[WebhookEvent] = []

    def subscribe(self, event_type: str, callback: WebhookSubscriber) -> None:
        """Subscribe a callback to a specific ``event_type`` (or ``"*"`` for all events)."""
        self._subscribers[event_type].append(callback)

    def emit(self, event_type: str, payload: dict[str, Any]) -> WebhookEvent:
        """Publish an event; subscriber and HTTP failures are logged and never raise."""
        event = WebhookEvent(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            timestamp=datetime.now(UTC).isoformat(),
            payload=payload,
        )
        self.recent_events.append(event)
        if len(self.recent_events) > 100:
            self.recent_events = self.recent_events[-100:]

        for key in (event_type, "*"):
            for callback in list(self._subscribers.get(key, ())):
                try:
                    callback(event)
                except Exception:
                    logger.warning(
                        "webhook subscriber failed",
                        extra={"event_type": event_type, "subscriber": getattr(callback, "__name__", "fn")},
                        exc_info=True,
                    )

        if self.target_url:
            self._deliver_http(event)
        return event

    def _deliver_http(self, event: WebhookEvent) -> None:
        body_bytes = json.dumps(event.to_dict(), sort_keys=True, default=str).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Analyst-Event": event.event_type,
            "X-Analyst-Delivery": event.event_id,
            "X-Analyst-Timestamp": event.timestamp,
        }
        if self.secret:
            headers["X-Analyst-Signature"] = sign_webhook_payload(self.secret, event.timestamp, body_bytes)
        try:
            resp = http.get_client().post(self.target_url, content=body_bytes, headers=headers, timeout=3.0)
            resp.raise_for_status()
        except Exception:
            logger.warning(
                "outbound webhook delivery failed",
                extra={"target_url": self.target_url, "event_type": event.event_type},
                exc_info=True,
            )
