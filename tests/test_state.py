from pathlib import Path

from beaconhill.state import (
    AppMode,
    AppState,
    EventType,
    RuntimeEvent,
    ToolExecutionState,
    ToolStatus,
    TurnPhase,
    TurnState,
)


class TestEnumValues:
    def test_app_mode_values(self):
        assert AppMode.INTERACTIVE == "interactive"
        assert AppMode.ONESHOT == "oneshot"
        assert AppMode.REPLAY == "replay"

    def test_turn_phase_values(self):
        assert TurnPhase.IDLE == "idle"
        assert TurnPhase.STARTING == "starting"
        assert TurnPhase.COMPACTING == "compacting"
        assert TurnPhase.CALLING_MODEL == "calling_model"
        assert TurnPhase.AWAITING_APPROVAL == "awaiting_approval"
        assert TurnPhase.RUNNING_TOOL == "running_tool"
        assert TurnPhase.STREAMING_FINAL == "streaming_final"
        assert TurnPhase.COMPLETED == "completed"
        assert TurnPhase.ERROR == "error"
        assert TurnPhase.INTERRUPTED == "interrupted"

    def test_tool_status_values(self):
        assert ToolStatus.REQUESTED == "requested"
        assert ToolStatus.APPROVAL_REQUIRED == "approval_required"
        assert ToolStatus.APPROVED == "approved"
        assert ToolStatus.DENIED == "denied"
        assert ToolStatus.RUNNING == "running"
        assert ToolStatus.SUCCEEDED == "succeeded"
        assert ToolStatus.FAILED == "failed"

    def test_event_type_values(self):
        assert EventType.TURN_STARTED == "turn_started"
        assert EventType.MODEL_CALL_STARTED == "model_call_started"
        assert EventType.MODEL_CALL_RETRYING == "model_call_retrying"
        assert EventType.TOOL_EXECUTION_STARTED == "tool_execution_started"
        assert EventType.TOOL_EXECUTION_FINISHED == "tool_execution_finished"
        assert EventType.ASSISTANT_STREAM_STARTED == "assistant_stream_started"
        assert EventType.ASSISTANT_STREAM_CHUNK == "assistant_stream_chunk"
        assert EventType.ASSISTANT_STREAM_FINISHED == "assistant_stream_finished"
        assert EventType.TURN_COMPLETED == "turn_completed"
        assert EventType.TURN_FAILED == "turn_failed"


class TestAppState:
    def test_construction(self):
        state = AppState(
            mode=AppMode.INTERACTIVE,
            model="gemma4:26b",
            host="http://localhost:11434",
            cwd=Path("/tmp"),
            session_id="abc123",
            session_path=Path("/tmp/abc123.jsonl"),
        )
        assert state.mode == AppMode.INTERACTIVE
        assert state.resumed is False

    def test_resumed_flag(self):
        state = AppState(
            mode=AppMode.INTERACTIVE,
            model="test",
            host="http://localhost:11434",
            cwd=Path("/tmp"),
            session_id="abc",
            session_path=Path("/tmp/abc.jsonl"),
            resumed=True,
        )
        assert state.resumed is True


class TestTurnState:
    def test_defaults(self):
        ts = TurnState(turn_index=0, user_input="hello")
        assert ts.phase == TurnPhase.STARTING
        assert ts.retry_count == 0
        assert ts.final_text is None
        assert ts.error_text is None
        assert ts.current_tool is None

    def test_phase_mutation(self):
        ts = TurnState(turn_index=1, user_input="test")
        ts.phase = TurnPhase.CALLING_MODEL
        assert ts.phase == TurnPhase.CALLING_MODEL
        ts.phase = TurnPhase.COMPLETED
        assert ts.phase == TurnPhase.COMPLETED


class TestToolExecutionState:
    def test_defaults(self):
        tool = ToolExecutionState(name="bash", arguments={"command": "ls"})
        assert tool.status == ToolStatus.REQUESTED
        assert tool.output is None
        assert tool.error_text is None

    def test_lifecycle(self):
        tool = ToolExecutionState(name="read_file", arguments={"file_path": "x.py"})
        tool.status = ToolStatus.RUNNING
        assert tool.status == ToolStatus.RUNNING
        tool.status = ToolStatus.SUCCEEDED
        tool.output = "file contents"
        assert tool.output == "file contents"

    def test_failure_state(self):
        tool = ToolExecutionState(name="bash", arguments={"command": "bad"})
        tool.status = ToolStatus.FAILED
        tool.error_text = "command not found"
        assert tool.error_text == "command not found"


class TestRuntimeEvent:
    def test_construction_defaults(self):
        event = RuntimeEvent(type=EventType.TURN_STARTED)
        assert event.type == EventType.TURN_STARTED
        assert event.timestamp  # auto-populated
        assert event.payload == {}

    def test_custom_payload(self):
        event = RuntimeEvent(
            type=EventType.MODEL_CALL_RETRYING,
            payload={"attempt": 1, "delay": 2},
        )
        assert event.payload["attempt"] == 1
        assert event.payload["delay"] == 2

    def test_timestamp_is_iso_format(self):
        event = RuntimeEvent(type=EventType.TURN_COMPLETED)
        # ISO format contains T separator and timezone info
        assert "T" in event.timestamp

    def test_separate_instances_get_independent_payloads(self):
        e1 = RuntimeEvent(type=EventType.TURN_STARTED)
        e2 = RuntimeEvent(type=EventType.TURN_COMPLETED)
        e1.payload["key"] = "val"
        assert "key" not in e2.payload
