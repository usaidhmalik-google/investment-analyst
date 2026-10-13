"""Conversation session storage selection (ADK session services).

``InMemorySessionService`` only works with a single instance. On Cloud Run with
autoscaling, a follow-up turn can reach a different instance, so production should
use ``vertex`` (Vertex AI Agent Engine managed sessions) or ``database`` (SQLAlchemy,
e.g. Cloud SQL for PostgreSQL via ``postgresql+asyncpg://...``).
"""

from __future__ import annotations

from google.adk.sessions import BaseSessionService, InMemorySessionService

from ..config import Settings


class SessionConfigError(ValueError):
    pass


def build_session_service(settings: Settings) -> BaseSessionService:
    backend = settings.session_backend
    if backend == "memory":
        return InMemorySessionService()
    if backend == "database":
        if not settings.session_db_url:
            raise SessionConfigError("SESSION_BACKEND=database requires SESSION_DB_URL")
        from google.adk.sessions import DatabaseSessionService

        return DatabaseSessionService(db_url=settings.session_db_url)
    if backend == "vertex":
        if not settings.agent_engine_id:
            raise SessionConfigError("SESSION_BACKEND=vertex requires AGENT_ENGINE_ID")
        from google.adk.sessions import VertexAiSessionService

        return VertexAiSessionService(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            agent_engine_id=settings.agent_engine_id,
        )
    raise SessionConfigError(f"Unknown SESSION_BACKEND: {backend}")  # pragma: no cover - guarded by Literal
