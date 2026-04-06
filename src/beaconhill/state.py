from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class AppMode(str, Enum):
    INTERACTIVE = "interactive"
    ONESHOT = "oneshot"
    REPLAY = "replay"


class TurnPhase(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    COMPACTING = "compacting"
    CALLING_MODEL = "calling_model"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING_TOOL = "running_tool"
    STREAMING_FINAL = "streaming_final"
    COMPLETED = "completed"
    ERROR = "error"
    INTERRUPTED = "interrupted"


class ToolStatus(str, Enum):
    REQUESTED = "requested"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    DENIED = "denied"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EventType(str, Enum):
    TURN_STARTED = "turn_started"
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_RETRYING = "model_call_retrying"
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_FINISHED = "tool_execution_finished"
    ASSISTANT_STREAM_STARTED = "assistant_stream_started"
    ASSISTANT_STREAM_CHUNK = "assistant_stream_chunk"
    ASSISTANT_STREAM_FINISHED = "assistant_stream_finished"
    TURN_COMPLETED = "turn_completed"
    TURN_FAILED = "turn_failed"


@dataclass
class AppState:
    mode: AppMode
    model: str
    host: str
    cwd: Path
    session_id: str
    session_path: Path
    resumed: bool = False


@dataclass
class ToolExecutionState:
    name: str
    arguments: dict[str, Any]
    status: ToolStatus = ToolStatus.REQUESTED
    output: str | None = None
    error_text: str | None = None


@dataclass
class TurnState:
    turn_index: int
    user_input: str
    phase: TurnPhase = TurnPhase.STARTING
    retry_count: int = 0
    final_text: str | None = None
    error_text: str | None = None
    current_tool: ToolExecutionState | None = None


@dataclass
class RuntimeEvent:
    type: EventType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, object] = field(default_factory=dict)
