"""Report persistence (document store) for audit trail, feedback and future LLM evaluations.

TDD: the final Markdown brief is written to Firestore alongside the prompt and
engagement metrics; thumbs-up/down feedback updates the same document.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from ..config import Settings

logger = logging.getLogger(__name__)


class ReportNotFoundError(KeyError):
    pass


class ReportStore(Protocol):
    async def save_report(self, report: dict[str, Any]) -> None: ...

    async def add_feedback(self, report_id: str, user: str, rating: str, comment: str | None) -> None: ...

    async def get_report(self, report_id: str) -> dict[str, Any] | None: ...


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class InMemoryReportStore:
    """Process-local store for local development and tests."""

    def __init__(self) -> None:
        self.reports: dict[str, dict[str, Any]] = {}

    async def save_report(self, report: dict[str, Any]) -> None:
        self.reports[report["report_id"]] = {**report, "created_at": report.get("created_at") or _now()}

    async def add_feedback(self, report_id: str, user: str, rating: str, comment: str | None) -> None:
        if report_id not in self.reports:
            raise ReportNotFoundError(report_id)
        self.reports[report_id]["feedback"] = {"user": user, "rating": rating, "comment": comment, "at": _now()}

    async def get_report(self, report_id: str) -> dict[str, Any] | None:
        return self.reports.get(report_id)


class FirestoreReportStore:
    """Firestore-backed store (collection ``FIRESTORE_COLLECTION``, one document per report)."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if client is None:  # pragma: no cover - requires GCP credentials
            from google.cloud import firestore

            client = firestore.Client(project=settings.google_cloud_project, database=settings.firestore_database)
        self._collection = client.collection(settings.firestore_collection)

    async def save_report(self, report: dict[str, Any]) -> None:
        doc = {**report, "created_at": report.get("created_at") or _now()}
        await asyncio.to_thread(self._collection.document(report["report_id"]).set, doc)

    async def add_feedback(self, report_id: str, user: str, rating: str, comment: str | None) -> None:
        ref = self._collection.document(report_id)
        snapshot = await asyncio.to_thread(ref.get)
        if not snapshot.exists:
            raise ReportNotFoundError(report_id)
        feedback = {"user": user, "rating": rating, "comment": comment, "at": _now()}
        await asyncio.to_thread(ref.update, {"feedback": feedback})

    async def get_report(self, report_id: str) -> dict[str, Any] | None:
        snapshot = await asyncio.to_thread(self._collection.document(report_id).get)
        return snapshot.to_dict() if snapshot.exists else None


def build_report_store(settings: Settings) -> ReportStore:
    if settings.persistence_backend == "firestore":
        return FirestoreReportStore(settings)
    return InMemoryReportStore()
