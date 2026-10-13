"""Auth (IAP), structured logging/tracing setup and FastAPI edge cases."""

from __future__ import annotations

import json
import logging
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider

from analyst import telemetry
from analyst.api import app as app_module
from analyst.api import auth
from analyst.api.app import _sse, create_app
from analyst.config import Settings, get_settings
from analyst.services.analyst_service import AnalystService, StreamEvent, UserIdentity
from analyst.services.report_store import InMemoryReportStore
from analyst.services.telemetry_sink import TelemetrySink
from analyst.telemetry import CloudLoggingJsonFormatter, configure_logging, configure_tracing

AUDIENCE = "/projects/123/global/backendServices/456"


def req(headers: dict[str, str] | None = None):
    return SimpleNamespace(headers=headers or {})


# --------------------------------------------------------------------------- auth


class TestResolveUserDev:
    def test_local_dev_default(self):
        assert auth.resolve_user(req(), Settings()) == UserIdentity(user_id="local-dev", email="local-dev")

    def test_email_header_parsed(self):
        user = auth.resolve_user(req({auth.IAP_EMAIL_HEADER: "accounts.google.com:analyst@malik.example"}), Settings())
        assert user == UserIdentity(user_id="analyst@malik.example", email="analyst@malik.example")

    def test_plain_email_header(self):
        assert auth.resolve_user(req({auth.IAP_EMAIL_HEADER: "a@b.c"}), Settings()).email == "a@b.c"

    def test_jwt_ignored_when_iap_not_required(self, monkeypatch):
        monkeypatch.setattr(auth, "verify_iap_jwt", lambda *a: pytest.fail("should not verify"))
        assert auth.resolve_user(req({auth.IAP_JWT_HEADER: "tok"}), Settings()).user_id == "local-dev"


class TestResolveUserIap:
    SETTINGS = Settings(REQUIRE_IAP=True, IAP_AUDIENCE=AUDIENCE)

    def test_missing_header_401(self):
        with pytest.raises(HTTPException) as info:
            auth.resolve_user(req(), self.SETTINGS)
        assert info.value.status_code == 401 and info.value.detail == "Missing IAP credentials"

    def test_missing_audience_401(self):
        with pytest.raises(HTTPException) as info:
            auth.resolve_user(req({auth.IAP_JWT_HEADER: "tok"}), Settings(REQUIRE_IAP=True))
        assert info.value.status_code == 401

    def test_invalid_token_401(self, monkeypatch):
        def reject(token, audience):
            raise ValueError("signature mismatch")

        monkeypatch.setattr(auth, "verify_iap_jwt", reject)
        with pytest.raises(HTTPException) as info:
            auth.resolve_user(req({auth.IAP_JWT_HEADER: "tok"}), self.SETTINGS)
        assert info.value.status_code == 401 and info.value.detail == "Invalid IAP credentials"

    def test_valid_token(self, monkeypatch):
        seen = []

        def verify(token, audience):
            seen.append((token, audience))
            return {"sub": "accounts.google.com:1234", "email": "pm@malik.example", "iss": auth.IAP_ISSUER}

        monkeypatch.setattr(auth, "verify_iap_jwt", verify)
        headers = {auth.IAP_JWT_HEADER: "tok", auth.IAP_EMAIL_HEADER: "accounts.google.com:spoofed@evil.example"}
        user = auth.resolve_user(req(headers), self.SETTINGS)
        assert user == UserIdentity(user_id="accounts.google.com:1234", email="pm@malik.example")
        assert seen == [("tok", AUDIENCE)]


class TestVerifyIapJwt:
    def test_checks_issuer_and_certs(self, monkeypatch):
        from google.oauth2 import id_token

        seen = {}

        def verify_token(token, request, audience, certs_url):
            seen.update(token=token, audience=audience, certs_url=certs_url)
            return {"iss": auth.IAP_ISSUER, "sub": "s"}

        monkeypatch.setattr(id_token, "verify_token", verify_token)
        assert auth.verify_iap_jwt("tok", AUDIENCE) == {"iss": auth.IAP_ISSUER, "sub": "s"}
        assert seen == {"token": "tok", "audience": AUDIENCE, "certs_url": auth.IAP_CERTS_URL}

    def test_wrong_issuer_rejected(self, monkeypatch):
        from google.oauth2 import id_token

        monkeypatch.setattr(id_token, "verify_token", lambda *a, **k: {"iss": "https://accounts.google.com"})
        with pytest.raises(ValueError, match="unexpected issuer"):
            auth.verify_iap_jwt("tok", AUDIENCE)


# --------------------------------------------------------------------------- logging / tracing


def log_record(msg="hello %s", args=("world",), level=logging.INFO, exc_info=None, **extra):
    record = logging.LogRecord("analyst.test", level, __file__, 10, msg, args, exc_info)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestJsonFormatter:
    def test_basic_payload_without_span(self):
        payload = json.loads(CloudLoggingJsonFormatter("proj").format(log_record()))
        assert payload["severity"] == "INFO" and payload["message"] == "hello world"
        assert payload["logger"] == "analyst.test" and payload["time"].endswith("+00:00")
        assert not any(k.startswith("logging.googleapis.com") for k in payload)

    def test_extras_included_private_excluded(self):
        record = log_record(level=logging.WARNING, ticker="NVDA", telemetry={"a": 1}, _private="x", obj=object())
        payload = json.loads(CloudLoggingJsonFormatter().format(record))
        assert payload["severity"] == "WARNING"
        assert payload["ticker"] == "NVDA" and payload["telemetry"] == {"a": 1}
        assert "_private" not in payload and payload["obj"].startswith("<object")
        assert "args" not in payload and "msg" not in payload

    def test_trace_fields_inside_active_span(self):
        tracer = TracerProvider().get_tracer("test")
        with tracer.start_as_current_span("op") as span:
            ctx = span.get_span_context()
            payload = json.loads(CloudLoggingJsonFormatter("my-proj").format(log_record()))
            bare = json.loads(CloudLoggingJsonFormatter().format(log_record()))
        trace_id = format(ctx.trace_id, "032x")
        assert payload["logging.googleapis.com/trace"] == f"projects/my-proj/traces/{trace_id}"
        assert payload["logging.googleapis.com/spanId"] == format(ctx.span_id, "016x")
        assert payload["logging.googleapis.com/trace_sampled"] is True
        assert bare["logging.googleapis.com/trace"] == trace_id

    def test_exception_included(self):
        try:
            raise ValueError("kaboom")
        except ValueError:
            record = log_record(level=logging.ERROR, exc_info=sys.exc_info())
        payload = json.loads(CloudLoggingJsonFormatter().format(record))
        assert "ValueError: kaboom" in payload["exception"]


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    noisy = {
        name: logging.getLogger(name).level
        for name in ("httpx", "httpcore", "urllib3", "google_adk", "yfinance", "peewee")
    }
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, lvl in noisy.items():
        logging.getLogger(name).setLevel(lvl)


class TestConfigure:
    def test_configure_logging(self, restore_root_logger):
        configure_logging(Settings(LOG_LEVEL="debug", GOOGLE_CLOUD_PROJECT="p1"))
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, CloudLoggingJsonFormatter)
        assert root.handlers[0].formatter.project_id == "p1"
        assert root.level == logging.DEBUG
        assert logging.getLogger("httpx").level == logging.WARNING

    def test_configure_logging_quiets_noisy_to_root_level(self, restore_root_logger):
        configure_logging(Settings(LOG_LEVEL="ERROR"))
        assert logging.getLogger("yfinance").level == logging.ERROR

    def test_configure_tracing_once(self, monkeypatch):
        installed = []
        monkeypatch.setattr(telemetry, "_configured_tracing", False)
        monkeypatch.setattr(telemetry.trace, "set_tracer_provider", installed.append)
        configure_tracing(Settings())
        configure_tracing(Settings())
        assert len(installed) == 1
        assert installed[0].resource.attributes["service.name"] == "investment-analyst-backend"

    def test_configure_tracing_with_cloud_trace(self, monkeypatch):
        import opentelemetry.exporter.cloud_trace as cloud_trace
        from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

        created = []

        class FakeExporter(SpanExporter):
            def __init__(self, project_id=None):
                created.append(project_id)

            def export(self, spans):
                return SpanExportResult.SUCCESS

        installed = []
        monkeypatch.setattr(cloud_trace, "CloudTraceSpanExporter", FakeExporter)
        monkeypatch.setattr(telemetry, "_configured_tracing", False)
        monkeypatch.setattr(telemetry.trace, "set_tracer_provider", installed.append)
        configure_tracing(Settings(ENABLE_CLOUD_TRACE=True, GOOGLE_CLOUD_PROJECT="proj-x"))
        assert created == ["proj-x"] and len(installed) == 1
        installed[0].shutdown()


# --------------------------------------------------------------------------- app edge cases


class FakeService:
    def __init__(self, *, run_exc=None, stream_events=(), stream_exc=None):
        self.run_exc = run_exc
        self.stream_events = list(stream_events)
        self.stream_exc = stream_exc
        self.store = InMemoryReportStore()
        self.telemetry = TelemetrySink(get_settings())

    async def run(self, body, user):
        raise self.run_exc

    async def stream(self, body, user):
        for event in self.stream_events:
            yield event
        if self.stream_exc:
            raise self.stream_exc


def parse_sse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def no_logging_reconfig(monkeypatch):
    monkeypatch.setattr(app_module, "configure_logging", lambda s: None)
    monkeypatch.setattr(app_module, "configure_tracing", lambda s: None)


@pytest.mark.usefixtures("no_logging_reconfig")
class TestApp:
    def test_sse_framing(self):
        assert _sse("token", {"text": "hi"}) == b'event: token\ndata: {"text": "hi"}\n\n'

    def test_chat_runtime_error_is_502(self):
        app = create_app(get_settings(), FakeService(run_exc=RuntimeError("Agent execution failed: X")))
        with TestClient(app) as client:
            resp = client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 502 and resp.json()["detail"] == "Agent execution failed: X"

    def test_stream_exception_keeps_sse_framing(self):
        svc = FakeService(stream_events=[StreamEvent("session", {"session_id": "s1"})], stream_exc=KeyError("boom"))
        with TestClient(create_app(get_settings(), svc)) as client:
            resp = client.post("/api/chat/stream", json={"message": "hi"})
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache" and resp.headers["x-accel-buffering"] == "no"
        assert parse_sse(resp.text) == [
            ("session", {"session_id": "s1"}),
            ("error", {"code": "internal_error", "message": "Unexpected server error."}),
        ]

    def test_iap_enforced_on_api_routes(self):
        settings = Settings(REQUIRE_IAP=True, IAP_AUDIENCE=AUDIENCE, ANALYST_OFFLINE_MODE=True)
        with TestClient(create_app(settings, FakeService())) as client:
            assert client.get("/healthz").status_code == 200
            assert client.get("/api/config").status_code == 401
            assert client.post("/api/chat", json={"message": "hi"}).status_code == 401

    def test_feedback_validation_and_audit(self):
        svc = FakeService()
        audits = []
        svc.telemetry.record_audit = lambda **kw: audits.append(kw)
        with TestClient(create_app(get_settings(), svc)) as client:
            assert client.post("/api/feedback", json={"report_id": "r", "rating": "meh"}).status_code == 422
            assert client.post("/api/feedback", json={"report_id": "missing", "rating": "up"}).status_code == 404
            svc.store.reports["r1"] = {"report_id": "r1"}
            ok = client.post(
                "/api/feedback",
                json={"report_id": "r1", "rating": "down", "comment": "wrong"},
                headers={auth.IAP_EMAIL_HEADER: "accounts.google.com:pm@malik.example"},
            )
        assert ok.json() == {"status": "ok"}
        assert svc.store.reports["r1"]["feedback"]["user"] == "pm@malik.example"
        assert audits == [
            {
                "user": "pm@malik.example",
                "action": "feedback_down",
                "tickers": [],
                "session_id": None,
                "report_id": "r1",
                "status": "ok",
            }
        ]

    def test_cors_preflight(self):
        settings = Settings(CORS_ORIGINS=["https://analyst.malik.example"])
        with TestClient(create_app(settings, FakeService())) as client:
            resp = client.options(
                "/api/chat",
                headers={"Origin": "https://analyst.malik.example", "Access-Control-Request-Method": "POST"},
            )
            bad = client.options(
                "/api/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
            )
        assert resp.headers["access-control-allow-origin"] == "https://analyst.malik.example"
        assert "access-control-allow-origin" not in bad.headers

    def test_lifespan_builds_default_service(self):
        app = create_app(get_settings())
        with TestClient(app) as client:
            assert client.get("/healthz").json() == {"status": "ok"}
            assert isinstance(app.state.service, AnalystService)
            assert isinstance(app.state.service.store, InMemoryReportStore)

    def test_session_id_validation(self):
        with TestClient(create_app(get_settings(), FakeService())) as client:
            assert client.post("/api/chat", json={"message": "hi", "session_id": "../etc"}).status_code == 422
            assert client.post("/api/chat", json={"message": "x" * 8001}).status_code == 422
