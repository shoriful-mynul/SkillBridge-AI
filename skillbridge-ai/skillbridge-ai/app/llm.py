"""LLM provider adapters.

One public entry point: `complete_json(...)`. It returns parsed JSON plus
metadata recording which provider and model actually answered.

Providers
---------
- gemini  (default) Google Gemini generateContent REST API.
- openai  Any OpenAI-compatible chat-completions API (OpenAI, Groq, OpenRouter).
- mock    Deterministic test doubles. The UI shows a TEST MODE banner. Never
          present mock output as AI output.

Robustness
----------
Gemini's REST field names for JSON output have changed between API versions,
and a live call is the only way to know which shape a key accepts. On a 400
INVALID_ARGUMENT we step through known payload shapes and remember the first
one that works for the life of the process. Model-not-found and rate limits
fall back to GEMINI_FALLBACK_MODEL. Every failure becomes an LLMError with a
plain-language message and a hint the UI can show.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from .config import Settings, get_settings

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Tests inject an httpx.MockTransport here. None means real network.
_TRANSPORT: Optional[httpx.AsyncBaseTransport] = None


class LLMError(Exception):
    def __init__(self, message: str, *, kind: str = "provider_error",
                 hint: str = "", status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.hint = hint
        self.status_code = status_code

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "hint": self.hint}


@dataclass
class LLMMeta:
    provider: str
    model: str
    latency_ms: int

    def to_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model, "latency_ms": self.latency_ms}


# --------------------------------------------------------------------------
# JSON parsing
# --------------------------------------------------------------------------
_FENCE_START = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_FENCE_END = re.compile(r"\s*```\s*$")


def parse_json_text(text: Optional[str]) -> Any:
    if not text or not text.strip():
        raise ValueError("empty response")
    t = _FENCE_END.sub("", _FENCE_START.sub("", text.strip())).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        return json.loads(t[start:end + 1])
    raise ValueError("no JSON object found in response")


JSON_REMINDER = (
    "\n\nIMPORTANT: Your previous reply could not be parsed. Reply with ONE valid "
    "JSON object only, exactly matching the requested schema. No markdown, no code "
    "fences, no commentary."
)


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------
_JSON_VARIANTS: list[Callable[[], dict]] = [
    lambda: {"responseMimeType": "application/json"},
    lambda: {"responseFormat": {"text": {"mimeType": "application/json"}}},
    lambda: {},  # prompt-only JSON; the parser strips fences
]
_GEMINI_COMPAT = {"json_variant": 0, "thinking": True, "system_instruction": True}


def reset_gemini_compat() -> None:
    _GEMINI_COMPAT.update({"json_variant": 0, "thinking": True, "system_instruction": True})


class _ModelNotFound(Exception):
    pass


class _RateLimited(Exception):
    pass


class _ServerError(Exception):
    pass


def _gemini_payload(system: str, user: str, s: Settings) -> dict:
    c = _GEMINI_COMPAT
    gen: dict = dict(_JSON_VARIANTS[c["json_variant"]]())
    if c["thinking"] and s.gemini_thinking_level and s.gemini_thinking_level != "off":
        gen["thinkingConfig"] = {"thinkingLevel": s.gemini_thinking_level}
    # Google's Gemini 3 guidance: keep temperature at its default (1.0); lower
    # values can cause looping or degraded output. Only send one if the user
    # explicitly overrides it.
    if s.temperature_override is not None:
        gen["temperature"] = s.temperature_override
    body: dict = {}
    if c["system_instruction"]:
        body["systemInstruction"] = {"parts": [{"text": system}]}
        body["contents"] = [{"role": "user", "parts": [{"text": user}]}]
    else:
        body["contents"] = [{"role": "user", "parts": [{"text": f"{system}\n\n---\n\n{user}"}]}]
    if gen:
        body["generationConfig"] = gen
    return body


def _gemini_ladder_step(low_msg: str) -> bool:
    """Downgrade one payload feature after a 400. Returns False when exhausted."""
    c = _GEMINI_COMPAT
    if "thinking" in low_msg and c["thinking"]:
        c["thinking"] = False
        return True
    if ("system_instruction" in low_msg or "systeminstruction" in low_msg) and c["system_instruction"]:
        c["system_instruction"] = False
        return True
    if c["json_variant"] < len(_JSON_VARIANTS) - 1:
        c["json_variant"] += 1
        return True
    if c["thinking"]:
        c["thinking"] = False
        return True
    if c["system_instruction"]:
        c["system_instruction"] = False
        return True
    return False


def _error_text(resp: httpx.Response) -> tuple[str, dict]:
    try:
        data = resp.json()
        err = data.get("error", {}) if isinstance(data, dict) else {}
        if isinstance(err, dict):
            return f"{err.get('status', '')} {err.get('message', '')}".strip(), data
        return str(err), data
    except Exception:
        return resp.text[:500], {}


def _retry_delay_seconds(data: dict) -> float:
    try:
        for d in data.get("error", {}).get("details", []):
            if "RetryInfo" in d.get("@type", ""):
                raw = str(d.get("retryDelay", "0s")).rstrip("s")
                return float(raw)
    except Exception:
        pass
    return 0.0


def _gemini_text(data: dict) -> str:
    cands = data.get("candidates") or []
    if not cands:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise LLMError(f"The AI provider blocked this request ({block}).", kind="blocked",
                           hint="Rephrase the input and try again.")
        raise LLMError("The AI provider returned no answer.", kind="empty", hint="Try again.")
    parts = ((cands[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    if not text.strip():
        reason = cands[0].get("finishReason") or "no reason given"
        raise LLMError(f"The AI provider returned an empty answer ({reason}).", kind="empty",
                       hint="Try again.")
    return text


async def _gemini_call(client: httpx.AsyncClient, s: Settings, model: str,
                       system: str, user: str) -> str:
    url = f"{GEMINI_BASE}/models/{model}:generateContent"
    headers = {"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"}
    ladder, rate_retries, server_retries = 0, 0, 0
    while True:
        try:
            resp = await client.post(url, headers=headers, json=_gemini_payload(system, user, s))
        except httpx.TimeoutException:
            if server_retries < 1:
                server_retries += 1
                continue
            raise LLMError("The AI provider timed out.", kind="timeout",
                           hint="Check your internet connection and try again.", status_code=504)
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach the AI provider ({exc.__class__.__name__}).",
                           kind="network",
                           hint="Check your internet connection. If venue Wi-Fi blocks it, use mobile data.",
                           status_code=503)

        if resp.status_code == 200:
            return _gemini_text(resp.json())

        msg, data = _error_text(resp)
        low = msg.lower()
        if ("api key not valid" in low or "api_key_invalid" in low
                or resp.status_code == 401
                or (resp.status_code == 403 and "permission" in low)):
            raise LLMError("The API key was rejected.", kind="auth",
                           hint="Check GEMINI_API_KEY in .env: paste the full key from "
                                "aistudio.google.com/apikey, no spaces or quotes.",
                           status_code=401)
        if "location is not supported" in low or "failed_precondition" in low:
            raise LLMError("Gemini isn't available from this network location.", kind="region",
                           hint="Try another network (mobile data), or set LLM_PROVIDER=openai with a "
                                "Groq or OpenAI key in .env.", status_code=503)
        if resp.status_code == 403:
            raise LLMError("This API key isn't allowed to make that request.", kind="forbidden",
                           hint="Create a fresh key at aistudio.google.com/apikey. If you're on a "
                                "restricted network, switch to mobile data.", status_code=403)
        if resp.status_code == 404:
            raise _ModelNotFound(msg)
        if resp.status_code == 429:
            delay = _retry_delay_seconds(data)
            if rate_retries < 2 and delay <= 20:
                rate_retries += 1
                await asyncio.sleep(min(max(delay, 2.0 * rate_retries), 8.0))
                continue
            raise _RateLimited(msg)
        if resp.status_code >= 500:
            if server_retries < 1:
                server_retries += 1
                await asyncio.sleep(1.5)
                continue
            raise _ServerError(msg)
        if resp.status_code == 400 and ladder < 6 and _gemini_ladder_step(low):
            ladder += 1
            continue
        raise LLMError(f"The AI provider rejected the request: {msg[:240]}", kind="bad_request",
                       hint="Check GEMINI_MODEL in .env. If this persists, set GEMINI_THINKING_LEVEL=off.")


async def _gemini_list_models(client: httpx.AsyncClient, s: Settings) -> list[str]:
    try:
        r = await client.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": s.gemini_api_key},
                             params={"pageSize": 200})
        if r.status_code != 200:
            return []
        names = []
        for m in r.json().get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                name = str(m.get("name", "")).removeprefix("models/")
                if "flash" in name or "pro" in name:
                    names.append(name)
        names.sort(key=lambda n: (not n.startswith("gemini-3"), n))
        return names
    except Exception:
        return []


async def _gemini_raw(system: str, user: str, s: Settings) -> tuple[str, str]:
    if not s.gemini_api_key:
        raise LLMError("No Gemini API key is configured.", kind="no_key",
                       hint="Add GEMINI_API_KEY to the .env file, then click 'Check connection'.",
                       status_code=503)
    models = [s.gemini_model]
    if s.gemini_fallback_model and s.gemini_fallback_model != s.gemini_model:
        models.append(s.gemini_fallback_model)
    last: Optional[Exception] = None
    async with httpx.AsyncClient(timeout=s.timeout_seconds, transport=_TRANSPORT) as client:
        for model in models:
            try:
                return await _gemini_call(client, s, model, system, user), model
            except (_ModelNotFound, _RateLimited, _ServerError) as exc:
                last = exc
                continue
        if isinstance(last, _ModelNotFound):
            available = await _gemini_list_models(client, s)
            hint = ("Set GEMINI_MODEL in .env to one of: " + ", ".join(available[:6])) if available \
                else "Set GEMINI_MODEL in .env to a current model such as gemini-3.8-flash."
            raise LLMError(f"Model '{s.gemini_model}' is not available for this API key.",
                           kind="model_not_found", hint=hint)
        if isinstance(last, _RateLimited):
            raise LLMError("The AI provider's rate limit was reached.", kind="rate_limit",
                           hint="Wait about a minute and retry. Free-tier keys allow a limited "
                                "number of requests per minute.", status_code=429)
        raise LLMError("The AI provider is having problems right now.", kind="provider_down",
                       hint="Retry in a moment.", status_code=503)


# --------------------------------------------------------------------------
# OpenAI-compatible (OpenAI, Groq, OpenRouter, ...)
# --------------------------------------------------------------------------
_OPENAI_COMPAT = {"json_mode": True}


async def _openai_raw(system: str, user: str, s: Settings) -> tuple[str, str]:
    if not s.openai_api_key:
        raise LLMError("No OpenAI-compatible API key is configured.", kind="no_key",
                       hint="Add OPENAI_API_KEY to the .env file, then click 'Check connection'.",
                       status_code=503)
    if not s.openai_model:
        raise LLMError("OPENAI_MODEL is not set.", kind="config",
                       hint="Set OPENAI_MODEL in .env to a model your provider offers.", status_code=503)
    url = f"{s.openai_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {s.openai_api_key}", "Content-Type": "application/json"}
    temperature = s.temperature_override if s.temperature_override is not None else 0.0
    rate_retries, server_retries = 0, 0
    async with httpx.AsyncClient(timeout=s.timeout_seconds, transport=_TRANSPORT) as client:
        while True:
            body: dict = {
                "model": s.openai_model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": temperature,
            }
            if _OPENAI_COMPAT["json_mode"]:
                body["response_format"] = {"type": "json_object"}
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.TimeoutException:
                if server_retries < 1:
                    server_retries += 1
                    continue
                raise LLMError("The AI provider timed out.", kind="timeout",
                               hint="Check your internet connection and try again.", status_code=504)
            except httpx.HTTPError as exc:
                raise LLMError(f"Could not reach the AI provider ({exc.__class__.__name__}).",
                               kind="network", hint="Check your internet connection.", status_code=503)
            if resp.status_code == 200:
                try:
                    return resp.json()["choices"][0]["message"]["content"] or "", s.openai_model
                except (KeyError, IndexError, TypeError):
                    raise LLMError("The AI provider returned an unexpected response.", kind="empty",
                                   hint="Try again.")
            msg, _ = _error_text(resp)
            if resp.status_code in (401, 403):
                raise LLMError("The API key was rejected.", kind="auth",
                               hint="Check OPENAI_API_KEY in .env.", status_code=401)
            if resp.status_code == 404:
                raise LLMError(f"Model '{s.openai_model}' was not found.", kind="model_not_found",
                               hint="Check OPENAI_MODEL and OPENAI_BASE_URL in .env.")
            if resp.status_code == 429:
                if rate_retries < 2:
                    rate_retries += 1
                    try:
                        wait = float(resp.headers.get("retry-after", "0"))
                    except ValueError:
                        wait = 0.0
                    await asyncio.sleep(min(max(wait, 2.0 * rate_retries), 8.0))
                    continue
                raise LLMError("The AI provider's rate limit was reached.", kind="rate_limit",
                               hint="Wait about a minute and retry.", status_code=429)
            if resp.status_code >= 500:
                if server_retries < 1:
                    server_retries += 1
                    await asyncio.sleep(1.5)
                    continue
                raise LLMError("The AI provider is having problems right now.",
                               kind="provider_down", hint="Retry in a moment.", status_code=503)
            if resp.status_code == 400 and _OPENAI_COMPAT["json_mode"] and "response_format" in msg.lower():
                _OPENAI_COMPAT["json_mode"] = False
                continue
            raise LLMError(f"The AI provider rejected the request: {msg[:240]}", kind="bad_request",
                           hint="Check OPENAI_MODEL in .env.")


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
async def complete_json(system: str, user: str, *, purpose: str,
                        context: Optional[dict] = None,
                        validate: Optional[Callable[[Any], Any]] = None) -> tuple[Any, LLMMeta]:
    """Call the configured provider and return (validated_json, meta).

    Retries once with a stricter reminder when the output is not valid JSON or
    fails schema validation.
    """
    s = get_settings()
    t0 = time.perf_counter()

    if s.provider == "mock":
        from . import mock_llm
        obj = mock_llm.respond(purpose, context or {})
        if validate:
            obj = validate(obj)
        return obj, LLMMeta("mock", "mock-test-double", int((time.perf_counter() - t0) * 1000))

    if s.provider == "gemini":
        raw = _gemini_raw
    elif s.provider == "openai":
        raw = _openai_raw
    else:
        raise LLMError(f"Unknown LLM_PROVIDER '{s.provider}'.", kind="config",
                       hint="Set LLM_PROVIDER in .env to gemini, openai or mock.", status_code=503)

    last_error: Optional[Exception] = None
    for attempt in (1, 2):
        text, model = await raw(system, user if attempt == 1 else user + JSON_REMINDER, s)
        try:
            obj = parse_json_text(text)
            if validate:
                obj = validate(obj)
            return obj, LLMMeta(s.provider, model, int((time.perf_counter() - t0) * 1000))
        except ValueError as exc:  # includes pydantic ValidationError
            last_error = exc
    raise LLMError("The AI returned a response we couldn't read.", kind="bad_output",
                   hint=f"Try again; this is usually a one-off. ({str(last_error)[:120]})")
