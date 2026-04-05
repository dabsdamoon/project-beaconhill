from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class Role(enum.StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ToolCall:
        return cls(name=d["name"], arguments=d["arguments"])


@dataclass
class Message:
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": str(self.role), "timestamp": self.timestamp}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls is not None:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Message:
        tool_calls = None
        if "tool_calls" in d:
            tool_calls = [ToolCall.from_dict(tc) for tc in d["tool_calls"]]
        return cls(
            role=Role(d["role"]),
            content=d.get("content"),
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
            timestamp=d.get("timestamp", ""),
        )

    def to_ollama(self) -> dict[str, Any]:
        """Convert to the dict format expected by the ollama library."""
        d: dict[str, Any] = {"role": str(self.role)}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls is not None:
            d["tool_calls"] = [
                {"function": {"name": tc.name, "arguments": tc.arguments}}
                for tc in self.tool_calls
            ]
        return d
