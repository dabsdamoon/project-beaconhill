"""Anthropic API client with the same interface as OllamaClient.

Used when the configured model name starts with `claude-` (e.g. `claude-haiku-4-5-20251001`).
The Beaconhill orchestrator/runtime is model-agnostic at the call boundary, so swapping
this in for OllamaClient lets the loop-first harness drive a cloud model.

Translation notes:
- Beaconhill messages use role=TOOL with tool_call_id holding the *tool name*
  (see runtime.py: `Message(role=Role.TOOL, ..., tool_call_id=tc.name)`).
- Anthropic uses tool_use blocks (assistant) + tool_result blocks (user) joined by
  a synthetic id. We assign deterministic ids during conversion and match TOOL
  messages to their tool_use ancestor in FIFO order keyed by tool name.
- SYSTEM messages are extracted out of the messages list and joined as the
  top-level `system` parameter (Anthropic's API requires this shape).

Caching modes (env BEACONHILL_CACHE_MODE):
- "off" (default): no cache_control anywhere. Every call pays full input price.
- "rolling": Option B — explicit cache_control on (a) the system prompt block and
  (b) the last block of the last message. The first lets the system text be read
  from cache on every subsequent call; the second causes the growing conversation
  prefix to be cached at the latest stable point so the next call only pays full
  price for its newly added turn.

Per-call usage is appended as a JSON line to BEACONHILL_USAGE_LOG (if set), so
the experiment can post-hoc sum input_tokens, cache_read_input_tokens, and
cache_creation_input_tokens across an entire run.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from anthropic import Anthropic, APIConnectionError, APIError, APITimeoutError, RateLimitError

from beaconhill.models import Message, Role, ToolCall

DEFAULT_REQUEST_TIMEOUT = 30.0  # Haiku 4.5 rarely takes >10s; 30s is generous.
DEFAULT_MAX_TOKENS = 8192
MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]
TIMEOUT_MAX_ATTEMPTS = 2
TIMEOUT_RETRY_DELAY = 15

RetryCallback = Callable[[int, int, str], None]

# Pricing per 1M tokens. Update when adding new models.
# https://docs.anthropic.com/en/docs/about-claude/pricing
_PRICING = {
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.10},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-opus-4-7":   {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
}


def _pricing_for(model: str) -> dict[str, float] | None:
    for key, prices in _PRICING.items():
        if model.startswith(key):
            return prices
    return None


def _compute_cost(model: str, usage: Any) -> float:
    p = _pricing_for(model)
    if p is None:
        return 0.0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    # Anthropic counts cache_creation/read tokens *separately* from input_tokens.
    return (inp * p["input"] + out * p["output"] + cw * p["cache_write"] + cr * p["cache_read"]) / 1_000_000.0


def _to_anthropic(
    messages: list[Message],
    cache_mode: str = "off",
) -> tuple[Any, list[dict[str, Any]]]:
    """Convert Beaconhill messages -> (system, anthropic_messages).

    `system` is either None, a string, or a list of content blocks (when caching).

    Tool plumbing: assistant.tool_calls become tool_use blocks with synthetic ids;
    subsequent role=TOOL messages become tool_result blocks in a user message,
    matched to tool_use ids by FIFO queues keyed on tool name.

    Cache placement (rolling mode):
    - System prompt: cache_control on the single text block (sticky, hits every call).
    - Last message of the conversation: cache_control on its last content block
      (rolling forward each call so the growing prefix is cached up to the latest
      stable point).
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    pending: dict[str, list[str]] = {}

    for msg_idx, m in enumerate(messages):
        if m.role == Role.SYSTEM:
            if m.content:
                system_parts.append(m.content)

        elif m.role == Role.USER:
            content = m.content or ""
            out.append({"role": "user", "content": content})

        elif m.role == Role.ASSISTANT:
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            if m.tool_calls:
                for i, tc in enumerate(m.tool_calls):
                    tu_id = f"toolu_{msg_idx:04d}_{i}"
                    blocks.append({"type": "tool_use", "id": tu_id, "name": tc.name, "input": tc.arguments})
                    pending.setdefault(tc.name, []).append(tu_id)
            # Anthropic rejects empty assistant content; fall back to a single space.
            out.append({"role": "assistant", "content": blocks if blocks else " "})

        elif m.role == Role.TOOL:
            name = m.tool_call_id or ""
            ids = pending.get(name)
            if ids:
                tu_id = ids.pop(0)
            else:
                # Orphan tool result (shouldn't happen if the producer is consistent).
                tu_id = f"toolu_orphan_{msg_idx:04d}"
            tr = {"type": "tool_result", "tool_use_id": tu_id, "content": m.content or ""}
            # Anthropic requires tool_result blocks in a user message immediately after
            # the assistant tool_use. Coalesce into the previous user msg if it's already
            # a content-list user msg; otherwise open a new user msg.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(tr)
            else:
                out.append({"role": "user", "content": [tr]})

    system_text = "\n\n".join(system_parts) if system_parts else None

    if cache_mode == "rolling":
        # System: convert to block list with cache_control on the (sole) text block.
        if system_text:
            system_out: Any = [{
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            system_out = None
        # Last message: place cache_control on the last block of its content.
        if out:
            last = out[-1]
            content = last["content"]
            if isinstance(content, str):
                # Promote string to a single-block list so cache_control can attach.
                last["content"] = [{
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }]
            elif isinstance(content, list) and content:
                # Attach to the last block (most recent tool_result or text).
                content[-1]["cache_control"] = {"type": "ephemeral"}
        return system_out, out

    return system_text, out


def _convert_tools(ollama_tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not ollama_tools:
        return None
    out = []
    for t in ollama_tools:
        fn = t.get("function", {})
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return out


def _classify_error(e: Exception) -> str:
    if isinstance(e, APITimeoutError):
        return "timeout"
    if isinstance(e, APIConnectionError):
        return "connection"
    if isinstance(e, RateLimitError):
        return "rate_limit"
    msg = str(e).lower()
    if "not found" in msg or "model" in msg and "invalid" in msg:
        return "model_not_found"
    return "unknown"


class AnthropicClient:
    """Drop-in replacement for OllamaClient when model name is `claude-*`."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key: str | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        cache_mode: str | None = None,
        usage_log: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Export it (e.g. from 1Password) before "
                "running with a claude-* model."
            )
        self.model = model
        self.max_tokens = max_tokens
        self._client = Anthropic(api_key=key, timeout=request_timeout, max_retries=0)
        self.max_retries = MAX_RETRIES
        # Caching + usage instrumentation. Default off to keep behavior identical to
        # the no-cache baseline; flip via env or kwarg for experiments.
        self.cache_mode = cache_mode or os.environ.get("BEACONHILL_CACHE_MODE", "off")
        if self.cache_mode not in ("off", "rolling"):
            raise ValueError(f"BEACONHILL_CACHE_MODE must be 'off' or 'rolling', got {self.cache_mode!r}")
        self.usage_log = usage_log or os.environ.get("BEACONHILL_USAGE_LOG") or None
        # Same surface as OllamaClient — runtime/orchestrator read these.
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        # Cloud-specific accounting.
        self.last_cost_usd = 0.0
        self.cumulative_cost_usd = 0.0
        self.cumulative_input_tokens = 0
        self.cumulative_output_tokens = 0
        self.cumulative_cache_read_tokens = 0
        self.cumulative_cache_creation_tokens = 0

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        on_retry: RetryCallback | None = None,
        format: str | dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> Message:
        # `format` is Ollama-only (forces JSON mode) — silently ignored on cloud.
        # `options` is Ollama's catch-all; we extract temperature and top_p here
        # because Beaconhill's planner sets temperature=0.2 for determinism.
        del format
        system, anth_messages = _to_anthropic(messages, cache_mode=self.cache_mode)
        anth_tools = _convert_tools(tools)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": anth_messages,
            "max_tokens": self.max_tokens,
        }
        if options:
            if "temperature" in options:
                kwargs["temperature"] = options["temperature"]
            if "top_p" in options:
                kwargs["top_p"] = options["top_p"]
        if system:
            kwargs["system"] = system
        if anth_tools:
            kwargs["tools"] = anth_tools

        response = self._call_with_retry(kwargs, on_retry=on_retry)
        return self._parse_response(response)

    def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        on_retry: RetryCallback | None = None,
    ) -> Iterator[str]:
        """Stream text content chunks. Tool calls are not surfaced via streaming;
        callers that need tool dispatch should use chat() / chat_or_stream()."""
        system, anth_messages = _to_anthropic(messages, cache_mode=self.cache_mode)
        anth_tools = _convert_tools(tools)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": anth_messages,
            "max_tokens": self.max_tokens,
        }
        if system:
            kwargs["system"] = system
        if anth_tools:
            kwargs["tools"] = anth_tools
        with self._client.messages.stream(**kwargs) as stream:
            for chunk in stream.text_stream:
                if chunk:
                    yield chunk
            final = stream.get_final_message()
        # Update token tracking from the streamed final message.
        self._record_usage(final.usage)

    def chat_or_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        on_retry: RetryCallback | None = None,
    ) -> tuple[Message | None, Iterator[str] | None]:
        """Mirror OllamaClient.chat_or_stream: chat first; if no tool calls, return
        a one-shot iterator over the response text so the runtime's streaming code
        path stays uniform. Avoids a second API call."""
        response = self.chat(messages, tools=tools, on_retry=on_retry)
        if response.tool_calls:
            return response, None
        text = response.content or ""

        def _chunks() -> Iterator[str]:
            if text:
                yield text

        return None, _chunks()

    def _call_with_retry(
        self,
        kwargs: dict[str, Any],
        on_retry: RetryCallback | None = None,
    ) -> Any:
        last_error: Exception | None = None
        attempt = 0
        max_attempts = MAX_RETRIES
        while attempt < max_attempts:
            try:
                return self._client.messages.create(**kwargs)
            except Exception as e:
                last_error = e
                kind = _classify_error(e)
                if kind == "model_not_found":
                    raise RuntimeError(f"Anthropic model '{self.model}' not found or invalid.") from e
                if kind == "connection":
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        if on_retry is not None:
                            on_retry(attempt + 1, delay, kind)
                        time.sleep(delay)
                        attempt += 1
                        continue
                    raise ConnectionError("Cannot reach Anthropic API.") from e
                if kind == "timeout":
                    if attempt < TIMEOUT_MAX_ATTEMPTS - 1:
                        if on_retry is not None:
                            on_retry(attempt + 1, TIMEOUT_RETRY_DELAY, kind)
                        time.sleep(TIMEOUT_RETRY_DELAY)
                        attempt += 1
                        continue
                    raise TimeoutError("Anthropic request timed out twice.") from e
                if kind == "rate_limit":
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt] * 2
                        if on_retry is not None:
                            on_retry(attempt + 1, delay, kind)
                        time.sleep(delay)
                        attempt += 1
                        continue
                    raise
                raise
        raise last_error  # type: ignore[misc]

    def _record_usage(self, usage: Any) -> None:
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.last_prompt_tokens = inp + cr + cw
        self.last_completion_tokens = out
        self.last_total_tokens = self.last_prompt_tokens + self.last_completion_tokens
        self.last_cost_usd = _compute_cost(self.model, usage)
        self.cumulative_cost_usd += self.last_cost_usd
        self.cumulative_input_tokens += inp
        self.cumulative_output_tokens += out
        self.cumulative_cache_read_tokens += cr
        self.cumulative_cache_creation_tokens += cw

        if self.usage_log:
            try:
                rec = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "model": self.model,
                    "cache_mode": self.cache_mode,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_read_input_tokens": cr,
                    "cache_creation_input_tokens": cw,
                    "cost_usd": self.last_cost_usd,
                }
                p = Path(self.usage_log)
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
            except Exception:
                # Never let usage logging break the run.
                pass

    def _parse_response(self, response: Any) -> Message:
        # response.content is a list of blocks: TextBlock and ToolUseBlock.
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(ToolCall(name=block.name, arguments=dict(block.input or {})))
        content = "".join(text_parts) if text_parts else None

        self._record_usage(response.usage)

        return Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        )
