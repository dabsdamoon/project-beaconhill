from __future__ import annotations

from collections.abc import Callable
from typing import Any

from beaconhill import ui
from beaconhill.client import OllamaClient
from beaconhill.context import compact_messages, needs_compaction
from beaconhill.models import Message, Role
from beaconhill.session import Session
from beaconhill.state import EventType, RuntimeEvent, ToolExecutionState, ToolStatus, TurnPhase, TurnState
from beaconhill.tools import Policy

EventSink = Callable[[RuntimeEvent], None]


def run_agentic_loop(
    client: OllamaClient,
    registry: "ToolRegistry",
    session: Session,
    tools: list[dict[str, Any]],
    allow_all: bool,
    context_limit: int,
    max_iterations: int,
    on_event: EventSink | None = None,
) -> TurnState:
    from beaconhill.tools import ToolRegistry  # for type only

    turn_state = TurnState(
        turn_index=_current_turn_index(session),
        user_input=_current_user_input(session),
        phase=TurnPhase.STARTING,
    )
    _emit(on_event, EventType.TURN_STARTED, turn_state=turn_state)

    def _handle_retry(attempt: int, delay: int, kind: str) -> None:
        turn_state.retry_count += 1
        _emit(
            on_event,
            EventType.MODEL_CALL_RETRYING,
            turn_state=turn_state,
            attempt=attempt,
            delay=delay,
            kind=kind,
        )
        label = "connection lost" if kind == "connection" else "timeout"
        ui.info(f"{label}, retrying in {delay}s... ({attempt}/{client.max_retries})")

    try:
        for _ in range(max_iterations):
            if needs_compaction(session.messages, context_limit=context_limit, client=client):
                turn_state.phase = TurnPhase.COMPACTING
                ui.info("Compacting context to stay focused...")
                session.messages = compact_messages(session.messages, client)

            turn_state.phase = TurnPhase.CALLING_MODEL
            _emit(on_event, EventType.MODEL_CALL_STARTED, turn_state=turn_state)

            model_pulse = ui.ThinkingPulse()
            model_pulse.start()
            try:
                response, text_stream = _chat_or_stream_with_optional_retry(
                    client,
                    session.messages,
                    tools,
                    _handle_retry,
                )
            finally:
                model_pulse.stop()

            if text_stream is not None:
                turn_state.phase = TurnPhase.STREAMING_FINAL
                _emit(on_event, EventType.ASSISTANT_STREAM_STARTED, turn_state=turn_state)
                chunks: list[str] = []
                for chunk in text_stream:
                    print(chunk, end="", flush=True)
                    chunks.append(chunk)
                    _emit(
                        on_event,
                        EventType.ASSISTANT_STREAM_CHUNK,
                        turn_state=turn_state,
                        chunk=chunk,
                    )
                print()
                full_text = "".join(chunks) or None
                turn_state.final_text = full_text
                session.append(Message(role=Role.ASSISTANT, content=full_text))
                _emit(on_event, EventType.ASSISTANT_STREAM_FINISHED, turn_state=turn_state)

                if client.last_prompt_tokens > 0:
                    ui.token_count(client.last_prompt_tokens, context_limit)
                turn_state.phase = TurnPhase.COMPLETED
                _emit(on_event, EventType.TURN_COMPLETED, turn_state=turn_state)
                return turn_state

            session.append(response)

            for tc in response.tool_calls:
                turn_state.current_tool = ToolExecutionState(name=tc.name, arguments=tc.arguments)
                policy = registry.check_permission(tc.name)

                if policy == Policy.DENY:
                    turn_state.current_tool.status = ToolStatus.DENIED
                    ui.tool_denied(tc.name)
                    tool_msg = Message(role=Role.TOOL, content="Permission denied", tool_call_id=tc.name)
                    session.append(tool_msg)
                    continue

                if policy == Policy.ASK and not allow_all:
                    turn_state.phase = TurnPhase.AWAITING_APPROVAL
                    turn_state.current_tool.status = ToolStatus.APPROVAL_REQUIRED
                    allowed = ui.permission_prompt(tc.name, tc.arguments)
                    if not allowed:
                        turn_state.current_tool.status = ToolStatus.DENIED
                        ui.tool_denied(tc.name, by_user=True)
                        tool_msg = Message(
                            role=Role.TOOL,
                            content="Permission denied by user",
                            tool_call_id=tc.name,
                        )
                        session.append(tool_msg)
                        continue
                    turn_state.current_tool.status = ToolStatus.APPROVED
                else:
                    turn_state.current_tool.status = ToolStatus.APPROVED

                turn_state.phase = TurnPhase.RUNNING_TOOL
                turn_state.current_tool.status = ToolStatus.RUNNING
                _emit(
                    on_event,
                    EventType.TOOL_EXECUTION_STARTED,
                    turn_state=turn_state,
                    tool=turn_state.current_tool,
                )
                ui.tool_start(tc.name, ui.summarize_args(tc.arguments))

                tool_pulse = ui.ThinkingPulse(label=f"running {tc.name}")
                tool_pulse.start()
                try:
                    result = registry.execute(tc.name, tc.arguments)
                finally:
                    tool_pulse.stop()

                if result.is_error:
                    turn_state.current_tool.status = ToolStatus.FAILED
                    turn_state.current_tool.error_text = result.output
                    ui.tool_error(result.output)
                else:
                    turn_state.current_tool.status = ToolStatus.SUCCEEDED

                turn_state.current_tool.output = result.output
                ui.tool_end()
                _emit(
                    on_event,
                    EventType.TOOL_EXECUTION_FINISHED,
                    turn_state=turn_state,
                    tool=turn_state.current_tool,
                    is_error=result.is_error,
                )

                tool_msg = Message(role=Role.TOOL, content=result.output, tool_call_id=tc.name)
                session.append(tool_msg)

        turn_state.phase = TurnPhase.ERROR
        turn_state.error_text = "Maximum iteration depth reached."
        ui.warning("Stepping back. Maximum iteration depth reached.")
        _emit(on_event, EventType.TURN_FAILED, turn_state=turn_state, reason="max_iterations")
        return turn_state
    except KeyboardInterrupt:
        turn_state.phase = TurnPhase.INTERRUPTED
        turn_state.error_text = "Interrupted."
        raise
    except Exception as exc:
        turn_state.phase = TurnPhase.ERROR
        turn_state.error_text = str(exc)
        _emit(on_event, EventType.TURN_FAILED, turn_state=turn_state, reason=str(exc))
        raise


def _current_turn_index(session: Session) -> int:
    return sum(1 for msg in session.messages if msg.role == Role.USER)


def _current_user_input(session: Session) -> str:
    for msg in reversed(session.messages):
        if msg.role == Role.USER:
            return msg.content or ""
    return ""


def _emit(on_event: EventSink | None, event_type: EventType, **payload: object) -> None:
    if on_event is None:
        return
    on_event(RuntimeEvent(type=event_type, payload=payload))


def _chat_or_stream_with_optional_retry(
    client: OllamaClient,
    messages: list[Message],
    tools: list[dict[str, Any]],
    on_retry: Callable[[int, int, str], None],
) -> tuple[Message | None, Any]:
    try:
        return client.chat_or_stream(messages, tools=tools, on_retry=on_retry)
    except TypeError as exc:
        if "unexpected keyword argument 'on_retry'" not in str(exc):
            raise
        return client.chat_or_stream(messages, tools=tools)
