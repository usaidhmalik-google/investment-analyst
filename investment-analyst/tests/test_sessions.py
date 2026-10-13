"""Session backend selection, including a real SQLite DatabaseSessionService round trip."""

from __future__ import annotations

import pytest
from google.adk.sessions import InMemorySessionService

from analyst.config import Settings
from analyst.services import sessions
from analyst.services.sessions import SessionConfigError, build_session_service


def _settings(**env) -> Settings:
    return Settings(**env)


def test_memory_default():
    assert isinstance(build_session_service(_settings()), InMemorySessionService)


def test_database_requires_url():
    with pytest.raises(SessionConfigError, match="SESSION_DB_URL"):
        build_session_service(_settings(SESSION_BACKEND="database"))


def test_vertex_requires_engine_id():
    with pytest.raises(SessionConfigError, match="AGENT_ENGINE_ID"):
        build_session_service(_settings(SESSION_BACKEND="vertex"))


def test_vertex_constructed_with_project_location(monkeypatch):
    captured = {}

    class FakeVertex:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import google.adk.sessions as adk_sessions

    monkeypatch.setattr(adk_sessions, "VertexAiSessionService", FakeVertex)
    svc = build_session_service(
        _settings(
            SESSION_BACKEND="vertex",
            AGENT_ENGINE_ID="123",
            GOOGLE_CLOUD_PROJECT="p",
            GOOGLE_CLOUD_LOCATION="us-central1",
        )
    )
    assert isinstance(svc, FakeVertex)
    assert captured == {"project": "p", "location": "us-central1", "agent_engine_id": "123"}


async def test_database_backend_persists_sessions_across_service_instances(tmp_path):
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("aiosqlite")
    url = f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}"
    settings = _settings(SESSION_BACKEND="database", SESSION_DB_URL=url)
    first = build_session_service(settings)
    created = await first.create_session(
        app_name="investment_analyst", user_id="alice", state={"evidence": {"Q:NVDA": {}}}
    )
    # A second instance (e.g. another Cloud Run replica) sees the same session.
    second = build_session_service(settings)
    loaded = await second.get_session(app_name="investment_analyst", user_id="alice", session_id=created.id)
    assert loaded is not None and "Q:NVDA" in loaded.state["evidence"]


def test_module_docstring_mentions_backends():
    assert "vertex" in sessions.__doc__ and "database" in sessions.__doc__
