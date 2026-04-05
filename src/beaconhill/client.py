from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any, Protocol

import ollama as ollama_lib

from beaconhill.models import Message, Role, ToolCall

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]


class LLMClient(Protocol):
    def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> Message: ...
    def stream(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> Iterator[str]: ...


def _classify_error(e: Exception) -> str:
    """Classify an Ollama error for user-friendly messaging."""
    msg = str(e).lower()
    if "connect" in msg or "refused" in msg:
        return "connection"
    if "not found" in msg or "pull" in msg:
        return "model_not_found"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    return "unknown"


class OllamaClient:
    def __init__(
        self,
        model: str = "gemma4:26b",
        host: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self._client = ollama_lib.Client(host=host)

    def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> Message:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_ollama() for m in messages],
        }
        if tools:
            kwargs["tools"] = tools

        response = self._call_with_retry(kwargs)
        return self._parse_response(response)

    def _call_with_retry(self, kwargs: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                return self._client.chat(**kwargs)
            except Exception as e:
                last_error = e
                kind = _classify_error(e)
                if kind == "model_not_found":
                    raise RuntimeError(
                        f"Model '{self.model}' not found. Run: ollama pull {self.model}"
                    ) from e
                if kind == "connection":
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        print(f"[connection lost, retrying in {delay}s... ({attempt + 1}/{MAX_RETRIES})]")
                        time.sleep(delay)
                        continue
                    raise ConnectionError(
                        f"Cannot connect to Ollama. Is `ollama serve` running?"
                    ) from e
                if kind == "timeout":
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        print(f"[timeout, retrying in {delay}s... ({attempt + 1}/{MAX_RETRIES})]")
                        time.sleep(delay)
                        continue
                raise
        raise last_error  # type: ignore[misc]

    def stream(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> Iterator[str]:
        """Stream text content chunks. Does not handle tool calls."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_ollama() for m in messages],
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        response_stream = self._call_with_retry(kwargs)
        for chunk in response_stream:
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content

    def chat_or_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[Message | None, Iterator[str] | None]:
        """Chat with tool-call detection.

        First tries non-streaming. If the response has tool calls, returns
        (Message, None). If no tool calls (final text), returns (None, stream)
        where stream yields text chunks for live display.
        """
        response = self.chat(messages, tools=tools)
        if response.tool_calls:
            return response, None

        # Final text response -- stream it for display
        # We already have the text, so yield it directly
        def _chunks() -> Iterator[str]:
            if response.content:
                yield response.content
        return None, _chunks()

    def _parse_response(self, response: Any) -> Message:
        msg = response.get("message", {})
        tool_calls = None
        raw_calls = msg.get("tool_calls")
        if raw_calls:
            tool_calls = [
                ToolCall(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                )
                for tc in raw_calls
            ]
        return Message(
            role=Role(msg.get("role", "assistant")),
            content=msg.get("content") or None,
            tool_calls=tool_calls,
        )
