from unittest.mock import MagicMock, patch

from beaconhill.models import Message, Role, ToolCall
from beaconhill.runtime import run_agentic_loop, _current_turn_index, _current_user_input, _emit
from beaconhill.session import Session
from beaconhill.state import EventType, RuntimeEvent, ToolStatus, TurnPhase
from beaconhill.tools import Permission, Policy, ToolRegistry, ToolResult, ToolSpec


def _make_registry(**policies) -> ToolRegistry:
    return ToolRegistry(policies={
        Permission.READ: policies.get("read", Policy.ALLOW),
        Permission.WRITE: policies.get("write", Policy.ALLOW),
        Permission.EXECUTE: policies.get("execute", Policy.ALLOW),
    })


def _session_with_user_msg(tmp_path, user_text="hello"):
    session = Session(model="test", session_dir=tmp_path)
    session.append(Message(role=Role.SYSTEM, content="system"))
    session.append(Message(role=Role.USER, content=user_text))
    return session


class TestHelpers:
    def test_current_turn_index(self, tmp_path):
        session = Session(model="test", session_dir=tmp_path)
        session.append(Message(role=Role.SYSTEM, content="sys"))
        assert _current_turn_index(session) == 0
        session.append(Message(role=Role.USER, content="q1"))
        assert _current_turn_index(session) == 1
        session.append(Message(role=Role.ASSISTANT, content="a1"))
        session.append(Message(role=Role.USER, content="q2"))
        assert _current_turn_index(session) == 2

    def test_current_user_input(self, tmp_path):
        session = Session(model="test", session_dir=tmp_path)
        session.append(Message(role=Role.SYSTEM, content="sys"))
        assert _current_user_input(session) == ""
        session.append(Message(role=Role.USER, content="first"))
        assert _current_user_input(session) == "first"
        session.append(Message(role=Role.ASSISTANT, content="reply"))
        session.append(Message(role=Role.USER, content="second"))
        assert _current_user_input(session) == "second"

    def test_emit_with_no_sink(self):
        # Should not raise
        _emit(None, EventType.TURN_STARTED)

    def test_emit_calls_sink(self):
        sink = MagicMock()
        _emit(sink, EventType.TURN_STARTED, key="val")
        sink.assert_called_once()
        event = sink.call_args[0][0]
        assert isinstance(event, RuntimeEvent)
        assert event.type == EventType.TURN_STARTED
        assert event.payload["key"] == "val"


class TestTextResponse:
    def test_streaming_text_completes_turn(self, tmp_path, capsys):
        mock_client = MagicMock()

        def _chunks():
            yield "the "
            yield "answer"

        mock_client.chat_or_stream.return_value = (None, _chunks())
        mock_client.last_prompt_tokens = 100

        session = _session_with_user_msg(tmp_path)
        registry = _make_registry()

        with patch("beaconhill.ui._use_color", return_value=False):
            result = run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
            )

        assert result.phase == TurnPhase.COMPLETED
        assert result.final_text == "the answer"
        assert result.turn_index == 1
        assert result.user_input == "hello"

        output = capsys.readouterr().out
        assert "the answer" in output

    def test_events_emitted_for_text_response(self, tmp_path):
        mock_client = MagicMock()

        def _chunks():
            yield "hi"

        mock_client.chat_or_stream.return_value = (None, _chunks())
        mock_client.last_prompt_tokens = 0

        events: list[RuntimeEvent] = []
        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False):
            run_agentic_loop(
                client=mock_client,
                registry=_make_registry(),
                session=session,
                tools=[],
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
                on_event=events.append,
            )

        types = [e.type for e in events]
        assert EventType.TURN_STARTED in types
        assert EventType.MODEL_CALL_STARTED in types
        assert EventType.ASSISTANT_STREAM_STARTED in types
        assert EventType.ASSISTANT_STREAM_CHUNK in types
        assert EventType.ASSISTANT_STREAM_FINISHED in types
        assert EventType.TURN_COMPLETED in types


class TestToolExecution:
    def test_tool_call_then_text(self, tmp_path, capsys):
        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="glob", arguments={"pattern": "*.py"})],
        )

        def _final():
            yield "done"

        call_count = [0]

        def side_effect(messages, tools=None, on_retry=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0

        registry = _make_registry()
        registry.register(ToolSpec(
            name="glob",
            description="find files",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.READ,
            fn=lambda args: "file1.py\nfile2.py",
        ))

        session = _session_with_user_msg(tmp_path, "find files")

        with patch("beaconhill.ui._use_color", return_value=False):
            result = run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=registry.to_ollama(),
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
            )

        assert result.phase == TurnPhase.COMPLETED
        assert result.final_text == "done"

        # Tool result should be in session
        tool_msgs = [m for m in session.messages if m.role == Role.TOOL]
        assert len(tool_msgs) == 1
        assert "file1.py" in tool_msgs[0].content

    def test_tool_events_emitted(self, tmp_path):
        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="test_tool", arguments={"x": "1"})],
        )

        def _final():
            yield "ok"

        call_count = [0]

        def side_effect(messages, tools=None, on_retry=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0

        registry = _make_registry()
        registry.register(ToolSpec(
            name="test_tool",
            description="test",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.READ,
            fn=lambda args: "output",
        ))

        events: list[RuntimeEvent] = []
        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False):
            run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=registry.to_ollama(),
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
                on_event=events.append,
            )

        types = [e.type for e in events]
        assert EventType.TOOL_EXECUTION_STARTED in types
        assert EventType.TOOL_EXECUTION_FINISHED in types

        # Check tool execution event payload
        tool_started = next(e for e in events if e.type == EventType.TOOL_EXECUTION_STARTED)
        assert tool_started.payload["tool"].name == "test_tool"

        tool_finished = next(e for e in events if e.type == EventType.TOOL_EXECUTION_FINISHED)
        assert tool_finished.payload["tool"].status == ToolStatus.SUCCEEDED

    def test_tool_error_sets_failed_status(self, tmp_path):
        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="bad", arguments={})],
        )

        def _final():
            yield "handled"

        call_count = [0]

        def side_effect(messages, tools=None, on_retry=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0

        registry = _make_registry()
        registry.register(ToolSpec(
            name="bad",
            description="bad tool",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.READ,
            fn=lambda args: (_ for _ in ()).throw(RuntimeError("boom")),
        ))

        events: list[RuntimeEvent] = []
        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False):
            run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=registry.to_ollama(),
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
                on_event=events.append,
            )

        tool_finished = next(e for e in events if e.type == EventType.TOOL_EXECUTION_FINISHED)
        assert tool_finished.payload["is_error"] is True
        assert tool_finished.payload["tool"].status == ToolStatus.FAILED


class TestPermissions:
    def test_denied_tool_skipped(self, tmp_path):
        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="bash", arguments={"command": "rm -rf /"})],
        )

        def _final():
            yield "ok"

        call_count = [0]

        def side_effect(messages, tools=None, on_retry=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0

        registry = ToolRegistry(policies={
            Permission.READ: Policy.ALLOW,
            Permission.WRITE: Policy.DENY,
            Permission.EXECUTE: Policy.DENY,
        })
        registry.register(ToolSpec(
            name="bash",
            description="run command",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.EXECUTE,
            fn=lambda args: "should not run",
        ))

        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False):
            result = run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=registry.to_ollama(),
                allow_all=False,
                context_limit=32768,
                max_iterations=50,
            )

        assert result.phase == TurnPhase.COMPLETED
        tool_msgs = [m for m in session.messages if m.role == Role.TOOL]
        assert any("denied" in (m.content or "").lower() for m in tool_msgs)

    def test_ask_policy_denied_by_user(self, tmp_path):
        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="write_file", arguments={"file_path": "x.py", "content": "bad"})],
        )

        def _final():
            yield "ok"

        call_count = [0]

        def side_effect(messages, tools=None, on_retry=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0

        registry = ToolRegistry(policies={
            Permission.READ: Policy.ALLOW,
            Permission.WRITE: Policy.ASK,
            Permission.EXECUTE: Policy.ASK,
        })
        registry.register(ToolSpec(
            name="write_file",
            description="write",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.WRITE,
            fn=lambda args: "should not run",
        ))

        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False), \
             patch("beaconhill.ui.permission_prompt", return_value=False):
            result = run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=registry.to_ollama(),
                allow_all=False,
                context_limit=32768,
                max_iterations=50,
            )

        tool_msgs = [m for m in session.messages if m.role == Role.TOOL]
        assert any("denied by user" in (m.content or "").lower() for m in tool_msgs)

    def test_allow_all_skips_approval(self, tmp_path):
        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="write_file", arguments={"file_path": "x.py", "content": "ok"})],
        )

        def _final():
            yield "written"

        call_count = [0]

        def side_effect(messages, tools=None, on_retry=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0

        registry = ToolRegistry(policies={
            Permission.READ: Policy.ALLOW,
            Permission.WRITE: Policy.ASK,
            Permission.EXECUTE: Policy.ASK,
        })
        registry.register(ToolSpec(
            name="write_file",
            description="write",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.WRITE,
            fn=lambda args: "written to disk",
        ))

        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False), \
             patch("beaconhill.ui.permission_prompt") as mock_prompt:
            result = run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=registry.to_ollama(),
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
            )

        # permission_prompt should never have been called
        mock_prompt.assert_not_called()
        assert result.phase == TurnPhase.COMPLETED


class TestMaxIterations:
    def test_reaches_max_iterations(self, tmp_path):
        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="loop", arguments={})],
        )

        mock_client = MagicMock()
        mock_client.chat_or_stream.return_value = (tool_msg, None)
        mock_client.last_prompt_tokens = 0

        registry = _make_registry()
        registry.register(ToolSpec(
            name="loop",
            description="loops",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.READ,
            fn=lambda args: "ok",
        ))

        events: list[RuntimeEvent] = []
        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False):
            result = run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=registry.to_ollama(),
                allow_all=True,
                context_limit=32768,
                max_iterations=3,
                on_event=events.append,
            )

        assert result.phase == TurnPhase.ERROR
        assert "Maximum iteration" in result.error_text
        assert mock_client.chat_or_stream.call_count == 3

        types = [e.type for e in events]
        assert EventType.TURN_FAILED in types


class TestErrorHandling:
    def test_exception_sets_error_phase(self, tmp_path):
        mock_client = MagicMock()
        mock_client.last_prompt_tokens = 0
        mock_client.chat_or_stream.side_effect = RuntimeError("model crashed")

        events: list[RuntimeEvent] = []
        session = _session_with_user_msg(tmp_path)

        import pytest
        with patch("beaconhill.ui._use_color", return_value=False), \
             pytest.raises(RuntimeError, match="model crashed"):
            run_agentic_loop(
                client=mock_client,
                registry=_make_registry(),
                session=session,
                tools=[],
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
                on_event=events.append,
            )

        types = [e.type for e in events]
        assert EventType.TURN_FAILED in types

    def test_keyboard_interrupt_sets_interrupted_phase(self, tmp_path):
        mock_client = MagicMock()
        mock_client.last_prompt_tokens = 0
        mock_client.chat_or_stream.side_effect = KeyboardInterrupt()

        session = _session_with_user_msg(tmp_path)

        import pytest
        with patch("beaconhill.ui._use_color", return_value=False), \
             pytest.raises(KeyboardInterrupt):
            result = run_agentic_loop(
                client=mock_client,
                registry=_make_registry(),
                session=session,
                tools=[],
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
            )


class TestRetryCallback:
    def test_retry_increments_count_and_emits_event(self, tmp_path):
        def _final():
            yield "recovered"

        call_count = [0]

        def side_effect(messages, tools=None, on_retry=None):
            call_count[0] += 1
            if call_count[0] == 1:
                # Simulate the runtime's retry handler being invoked
                if on_retry:
                    on_retry(1, 2, "connection")
                # Then succeed on retry internally
                return None, _final()
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0
        mock_client.max_retries = 3

        events: list[RuntimeEvent] = []
        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False):
            result = run_agentic_loop(
                client=mock_client,
                registry=_make_registry(),
                session=session,
                tools=[],
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
                on_event=events.append,
            )

        assert result.retry_count == 1
        types = [e.type for e in events]
        assert EventType.MODEL_CALL_RETRYING in types

        retry_event = next(e for e in events if e.type == EventType.MODEL_CALL_RETRYING)
        assert retry_event.payload["attempt"] == 1
        assert retry_event.payload["delay"] == 2
        assert retry_event.payload["kind"] == "connection"


class TestStateTransitions:
    """Verify that the turn state machine follows the expected phase sequence."""

    def test_text_response_phase_sequence(self, tmp_path):
        mock_client = MagicMock()

        def _chunks():
            yield "answer"

        mock_client.chat_or_stream.return_value = (None, _chunks())
        mock_client.last_prompt_tokens = 0

        phases: list[TurnPhase] = []

        def track_phases(event: RuntimeEvent):
            ts = event.payload.get("turn_state")
            if ts and hasattr(ts, "phase"):
                phases.append(ts.phase)

        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False):
            run_agentic_loop(
                client=mock_client,
                registry=_make_registry(),
                session=session,
                tools=[],
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
                on_event=track_phases,
            )

        # Expected: STARTING -> CALLING_MODEL -> STREAMING_FINAL -> ... -> COMPLETED
        assert phases[0] == TurnPhase.STARTING
        assert TurnPhase.CALLING_MODEL in phases
        assert TurnPhase.STREAMING_FINAL in phases
        assert phases[-1] == TurnPhase.COMPLETED

    def test_tool_then_text_phase_sequence(self, tmp_path):
        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="t", arguments={})],
        )

        def _final():
            yield "done"

        call_count = [0]

        def side_effect(messages, tools=None, on_retry=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0

        registry = _make_registry()
        registry.register(ToolSpec(
            name="t",
            description="test",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.READ,
            fn=lambda args: "ok",
        ))

        phases: list[TurnPhase] = []

        def track_phases(event: RuntimeEvent):
            ts = event.payload.get("turn_state")
            if ts and hasattr(ts, "phase"):
                phases.append(ts.phase)

        session = _session_with_user_msg(tmp_path)

        with patch("beaconhill.ui._use_color", return_value=False):
            run_agentic_loop(
                client=mock_client,
                registry=registry,
                session=session,
                tools=registry.to_ollama(),
                allow_all=True,
                context_limit=32768,
                max_iterations=50,
                on_event=track_phases,
            )

        assert TurnPhase.RUNNING_TOOL in phases
        assert TurnPhase.CALLING_MODEL in phases
        assert TurnPhase.COMPLETED in phases
