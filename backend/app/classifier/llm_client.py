"""
Provider-agnostic LLM transport.

The plan names the Claude API, but the requirement here is "a free key I already have",
so this speaks two dialects and treats them as interchangeable:

  * **OpenAI-compatible** ``POST {base_url}/chat/completions`` -- OpenRouter, Zhipu GLM,
    Moonshot Kimi, Groq, Gemini's compat layer, Cerebras, Mistral, local Ollama.
  * **Anthropic native** ``POST {base_url}/messages`` with a forced tool call, which is
    the sturdiest way to get schema-conformant JSON out of Claude.

Everything the pipeline needs from a model is "return one JSON object matching this
schema", so that is the only method exposed. Structured output is requested through
whatever mechanism the provider supports, and then *validated anyway* -- an unparseable
or schema-violating response is treated as an abstention rather than being coerced into
a fake answer.

Hard guarantees, because this runs live in front of an audience:
  - Every call is wrapped in a timeout.
  - A per-run call budget stops a large stream from draining a free tier.
  - Any failure -- network, auth, rate limit, malformed JSON -- degrades to the
    deterministic offline reasoner instead of raising.
  - Identical inputs hit an in-process cache, so re-running the demo is instant.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import LLMConfig, settings


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMUnavailable(RuntimeError):
    """Raised internally when a call cannot produce usable structured output.

    Callers catch this and fall back; it never propagates to a request handler.
    """


@dataclass
class LLMStats:
    """Live counters surfaced on the dashboard's reasoning-tier panel."""

    calls_attempted: int = 0
    calls_succeeded: int = 0
    calls_failed: int = 0
    cache_hits: int = 0
    budget_exhausted: int = 0
    total_latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    last_error: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> int:
        return int(self.total_latency_ms / self.calls_succeeded) if self.calls_succeeded else 0

    def to_dict(self) -> dict:
        return {
            "calls_attempted": self.calls_attempted,
            "calls_succeeded": self.calls_succeeded,
            "calls_failed": self.calls_failed,
            "cache_hits": self.cache_hits,
            "budget_exhausted": self.budget_exhausted,
            "avg_latency_ms": self.avg_latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "last_error": self.last_error,
            "recent_errors": self.errors[-5:],
        }

    def reset(self) -> None:
        self.__init__()      # type: ignore[misc]


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response.

    Models wrap JSON in prose or fences even when told not to, so this tries the
    cheapest interpretation first and works outward.
    """
    if not text:
        raise LLMUnavailable("empty response")

    candidate = text.strip()

    # 1. The whole thing is JSON.
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 2. Fenced block.
    fence = _JSON_FENCE.search(candidate)
    if fence:
        try:
            parsed = json.loads(fence.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # 3. Brace matching from the first '{'.
    start = candidate.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(candidate[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break

    raise LLMUnavailable("response contained no parseable JSON object")


class LLMClient:
    """Thin async client over whichever endpoint is configured."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or settings.llm
        self.stats = LLMStats()
        self._cache: dict[str, dict] = {}
        self._client: httpx.AsyncClient | None = None
        self._calls_this_run = 0
        self._semaphore = asyncio.Semaphore(max(1, self.config.concurrency))
        # Structured-output level actually in force. Starts at whatever the provider
        # preset claims and ratchets down when the endpoint rejects it, because free
        # routes vary and losing the whole tier over an unsupported field would be
        # a silly way to fail. Order: json_schema -> json_object -> none.
        self._json_mode = self.config.json_mode
        # Model actually in use. Swapped to the configured fallback once the primary
        # proves unavailable (404 unknown model, or a persistent 429).
        self._model = self.config.model
        self._degraded: list[str] = []

    # -- lifecycle ---------------------------------------------------------

    async def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout_seconds),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except RuntimeError:
                # Loop already gone (scripts that call asyncio.run more than once).
                # Nothing to release that the interpreter will not reclaim anyway.
                pass
        self._client = None

    def begin_run(self) -> None:
        """Reset the per-run call budget."""
        self._calls_this_run = 0

    @property
    def budget_remaining(self) -> int:
        return max(0, self.config.max_calls_per_run - self._calls_this_run)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    # -- headers / payloads ------------------------------------------------

    def _headers(self) -> dict[str, str]:
        cfg = self.config
        if cfg.is_anthropic_native:
            return {
                "x-api-key": cfg.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "content-type": "application/json",
        }
        if "openrouter.ai" in cfg.base_url:
            # Optional attribution headers; harmless elsewhere but OpenRouter uses them.
            headers["HTTP-Referer"] = "https://localhost:5173"
            headers["X-Title"] = "AI Revenue Recovery"
        return headers

    def _anthropic_payload(self, system: str, user: str, schema: dict) -> dict:
        """Force a tool call so Claude must emit schema-shaped arguments."""
        return {
            "model": self._model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": "record_diagnosis",
                    "description": "Record the payment failure diagnosis.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "record_diagnosis"},
        }

    def _openai_payload(self, system: str, user: str, schema: dict) -> dict:
        # The schema is restated in the prompt as well as in response_format. Belt and
        # braces: `json_object` mode guarantees valid JSON but says nothing about which
        # keys, and a degraded route may honour neither.
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"{user}\n\n"
                        "Respond with a single JSON object and nothing else. It must "
                        f"conform to this JSON Schema:\n{json.dumps(schema)}"
                    ),
                },
            ],
        }
        if self._json_mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "diagnosis",
                    "strict": True,
                    "schema": schema,
                },
            }
        elif self._json_mode == "json_object":
            payload["response_format"] = {"type": "json_object"}

        if self.config.is_openrouter and self.config.require_parameters and "response_format" in payload:
            # Without this OpenRouter may fall through to an upstream provider that
            # ignores response_format, which reads as a model failure but is a routing
            # one. Better to be told no than to be quietly downgraded.
            payload["provider"] = {"require_parameters": True}
        return payload

    def _degrade_json_mode(self) -> bool:
        """Step down one structured-output level. False when already at the bottom."""
        order = ("json_schema", "json_object", "none")
        try:
            nxt = order[order.index(self._json_mode) + 1]
        except (ValueError, IndexError):
            return False
        self._degraded.append(f"response_format {self._json_mode} rejected -> {nxt}")
        self._json_mode = nxt
        return True

    def _switch_to_fallback(self, why: str) -> bool:
        """Move to the spare model once. False when there is no spare left."""
        spare = self.config.fallback_model
        if not spare or self._model != self.config.model:
            return False
        self._degraded.append(f"{self._model} unavailable ({why}) -> {spare}")
        self._model = spare
        return True

    @staticmethod
    def _parse_anthropic(body: dict) -> tuple[dict, dict]:
        usage = body.get("usage") or {}
        for block in body.get("content") or []:
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                return block["input"], usage
        # No tool block: fall back to any text content.
        for block in body.get("content") or []:
            if block.get("type") == "text":
                return extract_json(block.get("text", "")), usage
        raise LLMUnavailable("anthropic response had no usable content block")

    @staticmethod
    def _parse_openai(body: dict) -> tuple[dict, dict]:
        usage = body.get("usage") or {}
        choices = body.get("choices") or []
        if not choices:
            # Some gateways surface upstream failures in the body with HTTP 200.
            err = body.get("error")
            if err:
                raise LLMUnavailable(f"provider error: {err.get('message', err)}")
            raise LLMUnavailable("no choices in response")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            # Some providers return content as parts.
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not content and message.get("tool_calls"):
            args = message["tool_calls"][0].get("function", {}).get("arguments", "")
            return extract_json(args), usage
        return extract_json(content or ""), usage

    # -- the one public method --------------------------------------------

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        cache_key: str | None = None,
    ) -> tuple[dict, int]:
        """Return ``(parsed_object, latency_ms)``.

        Raises `LLMUnavailable` on any failure so the caller can fall back cleanly.
        """
        if not self.enabled:
            raise LLMUnavailable("no API key configured")

        if cache_key and cache_key in self._cache:
            self.stats.cache_hits += 1
            return self._cache[cache_key], 0

        if self.budget_remaining <= 0:
            self.stats.budget_exhausted += 1
            raise LLMUnavailable(
                f"per-run call budget of {self.config.max_calls_per_run} exhausted"
            )

        cfg = self.config
        url = (
            f"{cfg.base_url.rstrip('/')}/messages"
            if cfg.is_anthropic_native
            else f"{cfg.base_url.rstrip('/')}/chat/completions"
        )

        last_error = "unknown"
        async with self._semaphore:
            for attempt in range(cfg.max_retries + 2):
                self._calls_this_run += 1
                self.stats.calls_attempted += 1
                start = time.perf_counter()
                try:
                    payload = (
                        self._anthropic_payload(system, user, schema)
                        if cfg.is_anthropic_native
                        else self._openai_payload(system, user, schema)
                    )
                    client = await self.client()
                    response = await client.post(url, json=payload, headers=self._headers())
                    status = response.status_code

                    if status in (400, 422) and not cfg.is_anthropic_native:
                        body_text = response.text.lower()
                        structured = any(
                            token in body_text
                            for token in ("response_format", "json_schema", "json_object", "schema")
                        )
                        if structured and self._degrade_json_mode():
                            last_error = f"HTTP {status}: {self._degraded[-1]}"
                            continue
                        if "provider" in body_text and "require_parameters" in body_text:
                            # No route honours strict schema; drop the constraint.
                            if self._degrade_json_mode():
                                last_error = "no route honours strict schema; relaxed"
                                continue

                    if status == 404 and self._switch_to_fallback("unknown model"):
                        last_error = self._degraded[-1]
                        continue

                    if status in (500, 502, 503, 529):
                        # "Model overloaded" is the single most likely live failure on a
                        # free tier, and it is exactly what the spare model is for. Note
                        # a busy model can burn the full timeout before answering 503,
                        # so this path is also the one that protects demo pacing.
                        if self._switch_to_fallback(f"upstream {status}"):
                            last_error = self._degraded[-1]
                            continue
                        raise LLMUnavailable(
                            f"provider unavailable ({status}): {response.text[:120]}"
                        )

                    if status == 402:
                        # OpenRouter's signal for "you owe money", not a transient fault.
                        raise LLMUnavailable(
                            "provider requires credit (402) -- the free daily allowance "
                            "is likely spent; offline reasoner takes over"
                        )

                    if status == 429:
                        retry_after = response.headers.get("Retry-After")
                        wait = None
                        if retry_after:
                            try:
                                wait = float(retry_after)
                            except ValueError:
                                wait = None
                        if wait is not None and wait <= 3.0 and attempt < cfg.max_retries + 1:
                            await asyncio.sleep(wait)
                            last_error = f"rate limited, honoured Retry-After={wait}s"
                            continue
                        if self._switch_to_fallback("rate limited"):
                            last_error = self._degraded[-1]
                            continue
                        raise LLMUnavailable(
                            "rate limited (429)"
                            + (f", Retry-After={retry_after}s" if retry_after else "")
                        )

                    if status in (401, 403):
                        raise LLMUnavailable(f"auth rejected ({status})")
                    if status >= 400:
                        raise LLMUnavailable(f"HTTP {status}: {response.text[:180]}")

                    body = response.json()
                    data, usage = (
                        self._parse_anthropic(body)
                        if cfg.is_anthropic_native
                        else self._parse_openai(body)
                    )

                    latency_ms = int((time.perf_counter() - start) * 1000)
                    self.stats.calls_succeeded += 1
                    self.stats.total_latency_ms += latency_ms
                    self.stats.prompt_tokens += int(
                        usage.get("input_tokens") or usage.get("prompt_tokens") or 0
                    )
                    self.stats.completion_tokens += int(
                        usage.get("output_tokens") or usage.get("completion_tokens") or 0
                    )
                    if cache_key:
                        self._cache[cache_key] = data
                    return data, latency_ms

                except (httpx.TimeoutException, asyncio.TimeoutError):
                    # A model that cannot answer inside the timeout is unusable for a
                    # live demo even if it is technically up. Treat it like an outage.
                    last_error = f"timeout after {cfg.timeout_seconds}s"
                    if self._switch_to_fallback("timeout"):
                        continue
                except (LLMUnavailable, httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"

                if attempt < cfg.max_retries + 1:
                    await asyncio.sleep(0.6 * (attempt + 1))

        self.stats.calls_failed += 1
        self.stats.last_error = last_error
        self.stats.errors.append(last_error)
        raise LLMUnavailable(last_error)

    async def health_check(self) -> dict:
        """Ping the provider with a trivial structured request.

        Wired to a dashboard button so a live-model claim can be verified on the spot
        instead of asserted.
        """
        if not self.enabled:
            return {
                "ok": False,
                "mode": "offline",
                "detail": "No API key configured -- deterministic reasoner in use.",
                "provider": self.config.provider,
                **self.runtime_dict(),
            }
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}, "echo": {"type": "string"}},
            "required": ["ok", "echo"],
            "additionalProperties": False,
        }
        try:
            data, latency = await self.complete_json(
                "You are a health check. Reply with JSON only.",
                'Return {"ok": true, "echo": "pong"}.',
                schema,
            )
            return {
                "ok": bool(data.get("ok", True)),
                "mode": "live",
                "provider": self.config.provider,
                "provider_label": self.config.provider_label,
                "latency_ms": latency,
                "echo": data.get("echo"),
                **self.runtime_dict(),
            }
        except LLMUnavailable as exc:
            return {
                "ok": False,
                "mode": "degraded",
                "provider": self.config.provider,
                "detail": str(exc),
                "hint": (
                    "Check LLM_API_KEY / LLM_BASE_URL / LLM_MODEL. The pipeline is "
                    "still fully functional on the deterministic reasoner."
                ),
                **self.runtime_dict(),
            }

    def runtime_dict(self) -> dict:
        """What the transport actually settled on, as opposed to what was configured.

        Worth showing: "configured for strict json_schema on GLM, running json_object on
        the fallback" is the kind of thing that otherwise silently changes the meaning
        of the reasoning-tier numbers.
        """
        return {
            "active_model": self._model,
            "configured_model": self.config.model,
            "active_json_mode": self._json_mode,
            "configured_json_mode": self.config.json_mode,
            "using_fallback_model": self._model != self.config.model,
            "degradations": list(self._degraded),
            "calls_this_run": self._calls_this_run,
            "budget_remaining": self.budget_remaining,
        }


# Single shared client for the process.
llm_client = LLMClient()
