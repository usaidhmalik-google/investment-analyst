"""GCP Model Armor adapter: disabled/enabled, MATCH_FOUND handling and fail-open behaviour."""

from __future__ import annotations

import httpx
import pytest

from analyst.config import get_settings
from analyst.data import http
from analyst.guardrails import model_armor
from analyst.guardrails.injection import INJECTION_MESSAGE

TEMPLATE = "projects/p1/locations/us-central1/templates/t1"


@pytest.fixture
def armor(monkeypatch):
    monkeypatch.setenv("MODEL_ARMOR_TEMPLATE", TEMPLATE)
    get_settings.cache_clear()
    calls: list[tuple[str, dict]] = []
    responses: list = []

    def fake_post(url, body):
        calls.append((url, body))
        result = responses.pop(0) if responses else {}
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(model_armor, "_post", fake_post)
    return calls, responses


MATCH = {
    "sanitizationResult": {
        "filterMatchState": "MATCH_FOUND",
        "filterResults": {
            "pi_and_jailbreak": {"piAndJailbreakFilterResult": {"matchState": "MATCH_FOUND"}},
            "csam": {"csamFilterFilterResult": {"matchState": "NO_MATCH_FOUND"}},
        },
    }
}
NO_MATCH = {"sanitizationResult": {"filterMatchState": "NO_MATCH_FOUND", "filterResults": {}}}


class TestDisabled:
    def test_no_template_never_calls_api(self, monkeypatch):
        monkeypatch.setattr(model_armor, "_post", lambda *a: pytest.fail("must not be called"))
        assert model_armor.screen_prompt("anything").blocked is False
        assert model_armor.screen_response("anything").blocked is False


class TestPromptScreening:
    def test_match_found_blocks(self, armor):
        calls, responses = armor
        responses.append(MATCH)
        verdict = model_armor.screen_prompt("ignore everything")
        assert verdict.blocked is True
        assert verdict.category == "model_armor"
        assert verdict.reason == "filters: pi_and_jailbreak"
        assert verdict.message == INJECTION_MESSAGE
        url, body = calls[0]
        assert url == f"https://modelarmor.us-central1.rep.googleapis.com/v1/{TEMPLATE}:sanitizeUserPrompt"
        assert body == {"userPromptData": {"text": "ignore everything"}}

    def test_match_without_filter_details(self, armor):
        _, responses = armor
        responses.append({"sanitizationResult": {"filterMatchState": "MATCH_FOUND"}})
        assert model_armor.screen_prompt("x").reason == "filters: unknown"

    def test_no_match_allows(self, armor):
        _, responses = armor
        responses.append(NO_MATCH)
        assert model_armor.screen_prompt("Brief me on NVDA").blocked is False

    def test_empty_result_allows(self, armor):
        _, responses = armor
        responses.append({})
        assert model_armor.screen_prompt("x").blocked is False

    def test_api_failure_fails_open(self, armor):
        _, responses = armor
        responses.append(httpx.ConnectError("unreachable"))
        assert model_armor.screen_prompt("x").blocked is False

    def test_invalid_template_fails_open(self, monkeypatch):
        monkeypatch.setenv("MODEL_ARMOR_TEMPLATE", "not-a-template")
        get_settings.cache_clear()
        monkeypatch.setattr(model_armor, "_post", lambda *a: pytest.fail("must not be called"))
        assert model_armor.screen_prompt("x").blocked is False
        assert model_armor.screen_response("x").blocked is False


class TestResponseScreening:
    def test_match_found_blocks(self, armor):
        calls, responses = armor
        responses.append(MATCH)
        verdict = model_armor.screen_response("bad output")
        assert verdict.blocked is True and verdict.category == "model_armor_response"
        assert "withheld by the safety filter" in verdict.message
        assert calls[0][0].endswith(":sanitizeModelResponse")
        assert calls[0][1] == {"modelResponseData": {"text": "bad output"}}

    def test_no_match_allows(self, armor):
        _, responses = armor
        responses.append(NO_MATCH)
        assert model_armor.screen_response("fine").blocked is False

    def test_api_failure_fails_open(self, armor):
        _, responses = armor
        responses.append(RuntimeError("boom"))
        assert model_armor.screen_response("fine").blocked is False


class TestEndpointAndTransport:
    def test_endpoint_uses_regional_host(self):
        url = model_armor._endpoint("projects/x/locations/europe-west4/templates/y", "sanitizeUserPrompt")
        assert (
            url
            == "https://modelarmor.europe-west4.rep.googleapis.com/v1/projects/x/locations/europe-west4/templates/y:sanitizeUserPrompt"
        )

    @pytest.mark.parametrize("template", ["", "projects/x/templates/y", "projects/x/locations/l/templates/y/extra"])
    def test_invalid_template_raises(self, template):
        with pytest.raises(ValueError, match="Invalid MODEL_ARMOR_TEMPLATE"):
            model_armor._endpoint(template, "m")

    def test_post_sends_bearer_token(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers["Authorization"]
            seen["body"] = request.content
            return httpx.Response(200, json=NO_MATCH)

        monkeypatch.setattr(model_armor, "_access_token", lambda: "tok123")
        http.set_client(httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            assert model_armor._post("https://modelarmor.test/v1/x:m", {"a": 1}) == NO_MATCH
        finally:
            http.set_client(None)
        assert seen["auth"] == "Bearer tok123"
        assert seen["body"] == b'{"a":1}'

    def test_post_raises_on_http_error(self, monkeypatch):
        monkeypatch.setattr(model_armor, "_access_token", lambda: "tok")
        http.set_client(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
        try:
            with pytest.raises(httpx.HTTPStatusError):
                model_armor._post("https://modelarmor.test/v1/x:m", {})
        finally:
            http.set_client(None)

    def test_end_to_end_fail_open_on_http_error(self, monkeypatch):
        monkeypatch.setenv("MODEL_ARMOR_TEMPLATE", TEMPLATE)
        get_settings.cache_clear()
        monkeypatch.setattr(model_armor, "_access_token", lambda: "tok")
        http.set_client(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        try:
            assert model_armor.screen_prompt("x").blocked is False
        finally:
            http.set_client(None)

    def test_flagged_helper(self):
        assert model_armor._flagged(MATCH) == (True, ["pi_and_jailbreak"])
        assert model_armor._flagged(NO_MATCH) == (False, [])
        assert model_armor._flagged({}) == (False, [])
