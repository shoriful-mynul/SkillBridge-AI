"""Provider adapter tests against simulated HTTP responses (no network)."""
import asyncio
import json

import httpx
import pytest

from app import llm


def _gemini_ok(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": text}]},
                            "finishReason": "STOP"}]}


@pytest.fixture(autouse=True)
def gemini_env(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    llm.reset_gemini_compat()
    real_sleep = asyncio.sleep

    async def no_wait(*_):
        await real_sleep(0)

    monkeypatch.setattr(llm.asyncio, "sleep", no_wait)
    yield
    llm._TRANSPORT = None


def _run(handler):
    llm._TRANSPORT = httpx.MockTransport(handler)
    return asyncio.run(llm.complete_json("sys", "user", purpose="t"))


def test_parse_json_variants():
    assert llm.parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json_text('Sure! {"a": 2} hope that helps') == {"a": 2}
    with pytest.raises(ValueError):
        llm.parse_json_text("no json here")


def test_success_skips_thought_parts_and_sends_key_header():
    seen = {}

    def handler(req):
        seen["key"] = req.headers.get("x-goog-api-key")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_gemini_ok('{"ok": true}'))

    obj, meta = _run(handler)
    assert obj == {"ok": True} and meta.model == "gemini-3.8-flash"
    assert seen["key"] == "test-key"
    gen = seen["body"]["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    assert "temperature" not in gen          # Gemini 3: keep provider default
    assert gen["thinkingConfig"]["thinkingLevel"] == "low"


def test_400_unknown_field_walks_the_payload_ladder():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body.get("generationConfig", {}))
        if "responseMimeType" in body.get("generationConfig", {}):
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT",
                                                       "message": 'Unknown name "responseMimeType"'}})
        return httpx.Response(200, json=_gemini_ok('{"ok": 1}'))

    obj, _ = _run(handler)
    assert obj == {"ok": 1}
    assert "responseFormat" in calls[-1]
    # remembered for the next call
    obj, _ = _run(handler)
    assert len(calls) == 3


def test_404_falls_back_to_second_model():
    def handler(req):
        if "gemini-3.8-flash:" in str(req.url):
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND", "message": "not found"}})
        return httpx.Response(200, json=_gemini_ok('{"ok": true}'))

    _, meta = _run(handler)
    assert meta.model == "gemini-3.5-flash-lite"


def test_both_models_missing_lists_alternatives():
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]}]})
        return httpx.Response(404, json={"error": {"status": "NOT_FOUND", "message": "nope"}})

    with pytest.raises(llm.LLMError) as e:
        _run(handler)
    assert e.value.kind == "model_not_found" and "gemini-3.6-flash" in e.value.hint


def test_invalid_key_is_reported_not_retried():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid. Please pass a valid API key."}})

    with pytest.raises(llm.LLMError) as e:
        _run(handler)
    assert e.value.kind == "auth" and len(calls) == 1


def test_rate_limit_retries_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "slow down",
                                                       "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3s"}]}})
        return httpx.Response(200, json=_gemini_ok('{"ok": true}'))

    obj, _ = _run(handler)
    assert obj == {"ok": True} and len(calls) == 2


def test_unparseable_output_retried_once_with_reminder():
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json=_gemini_ok("oops not json" if len(calls) == 1 else '{"ok": true}'))

    obj, _ = _run(handler)
    assert obj == {"ok": True}
    assert "could not be parsed" in calls[1]["contents"][0]["parts"][0]["text"]


def test_no_key_gives_actionable_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with pytest.raises(llm.LLMError) as e:
        asyncio.run(llm.complete_json("s", "u", purpose="t"))
    assert e.value.kind == "no_key" and ".env" in e.value.hint


def test_network_failure_is_friendly():
    def handler(req):
        raise httpx.ConnectError("boom")

    with pytest.raises(llm.LLMError) as e:
        _run(handler)
    assert e.value.kind == "network"


def test_openai_compatible_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "some-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    obj, meta = _run(handler)
    assert obj == {"ok": True} and meta.model == "some-model"
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["body"]["temperature"] == 0.0 and seen["body"]["response_format"]["type"] == "json_object"


def test_region_and_forbidden_errors_are_explained():
    def region(req):
        return httpx.Response(400, json={"error": {"status": "FAILED_PRECONDITION", "message": "User location is not supported for the API use."}})

    with pytest.raises(llm.LLMError) as e:
        _run(region)
    assert e.value.kind == "region"

    def forbidden(req):
        return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED", "message": "Generative Language API has not been used in project"}})

    with pytest.raises(llm.LLMError) as e:
        _run(forbidden)
    assert e.value.kind in {"auth", "forbidden"}
