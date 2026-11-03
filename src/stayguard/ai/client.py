"""LLM client: one small interface, a real Anthropic implementation and a scripted fake for tests.

Every call asks for structured JSON (output_config.format), so responses are valid JSON by
construction. The API key comes from the environment or .env, never from code (CLAUDE.md §2).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from dotenv import load_dotenv

from stayguard.config import PROJECT_ROOT

DEFAULT_MODEL = "claude-sonnet-5-5"  # CLAUDE.md §2; override with ANTHROPIC_MODEL
# Models that accept server-side refusal fallbacks in the "default" form on the Claude API.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class AIError(RuntimeError):
    """A failure the app should show as a friendly message (not a stack trace)."""


@dataclass
class LLMResponse:
    data: dict[str, Any]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms: int = 0


class LLMClient(Protocol):
    model: str

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4000
    ) -> LLMResponse: ...


def load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def has_api_key() -> bool:
    load_env()
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def configured_model() -> str:
    load_env()
    return os.getenv("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL


class AnthropicClient:
    """Claude via the official SDK, with structured JSON output and a cached system prompt."""

    def __init__(self, model: str | None = None, effort: str = "medium") -> None:
        import anthropic  # imported lazily so the app and tests run without the network

        load_env()
        if not has_api_key():
            raise AIError("No ANTHROPIC_API_KEY found. Add it to .env to use live AI features.")
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(timeout=90.0, max_retries=2)
        self.model = model or configured_model()
        self.effort = effort

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4000
    ) -> LLMResponse:
        anthropic = self._anthropic
        extra: dict[str, Any] = {}
        if self.model in FALLBACK_MODELS:
            # If a safety classifier declines, the API re-runs on a fallback model in-call.
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        started = time.perf_counter()
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                # The system prompt (schema, rules, examples) is identical across calls: cache it.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                **extra,
            )
        except anthropic.AuthenticationError as e:
            raise AIError("The Anthropic API key was rejected. Check .env.") from e
        except anthropic.RateLimitError as e:
            raise AIError("The AI service is rate-limited right now. Try again shortly.") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"The AI service returned an error ({e.status_code}).") from e
        except anthropic.APIConnectionError as e:
            raise AIError("Could not reach the AI service. Check the network.") from e
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.stop_reason == "refusal":
            raise AIError("The AI declined to answer this request.")
        if response.stop_reason == "max_tokens":
            raise AIError("The AI response was cut off; try a narrower question.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AIError("The AI returned an unreadable response.") from e
        usage = response.usage
        return LLMResponse(
            data=data,
            model=response.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            latency_ms=latency_ms,
        )


@dataclass
class ScriptedClient:
    """Test double: returns queued responses (dicts, or callables of (system, user) -> dict)."""

    responses: list[dict[str, Any] | Callable[[str, str], dict[str, Any]]] = field(
        default_factory=list
    )
    model: str = "scripted-test-model"
    calls: list[dict[str, str]] = field(default_factory=list)

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4000
    ) -> LLMResponse:
        self.calls.append({"system": system, "user": user})
        if not self.responses:
            raise AIError("ScriptedClient ran out of responses")
        item = self.responses.pop(0)
        data = item(system, user) if callable(item) else item
        return LLMResponse(data=data, model=self.model, input_tokens=100, output_tokens=50)
