# Beaconhill State Modeling Plan

## Purpose

This document defines a concrete state-modeling plan for Beaconhill's terminal UX and runtime orchestration.

The goal is to move Beaconhill from a "styled REPL with print helpers" to an explicit, inspectable agent runtime whose UI reflects real execution state. This is the main difference between Beaconhill's current UI and more operationally mature agent interfaces like Claude Code or Codex.

This plan does not change Beaconhill's product direction. It changes how the runtime represents and renders work.

---

## First Step: Minimal Viable Implementation

Before reading the full analysis, here is the concrete first deliverable. This is the primary design. Everything else in this document is context and future expansion.

1. Add `TurnPhase` and `ToolExecutionState` to a new `src/beaconhill/state.py`.
2. Introduce a `TurnState` object inside the main loop.
3. Move retry notices out of `client.py` via an `on_retry` callback.
4. Have the runtime call existing named UI functions (`tool_start`, `tool_end`, etc.) at well-defined state transitions, instead of `cli.py` calling them inline.

That alone materially improves UI clarity without a full architecture rewrite.

---

## Problem Statement

Beaconhill already has runtime state, but most of it is implicit in control flow rather than represented directly in data structures.

Examples from the current code:

- [cli.py](/Users/dabsdamoon/projects/project-beaconhill/src/beaconhill/cli.py) owns turn orchestration, permission flow, session mutation, and much of the presentation sequencing.
- [ui.py](/Users/dabsdamoon/projects/project-beaconhill/src/beaconhill/ui.py) provides print helpers and a pulse animation, but it does not render from a shared state object.
- [client.py](/Users/dabsdamoon/projects/project-beaconhill/src/beaconhill/client.py) prints retry notices directly, which bypasses UI control.

This creates several issues:

- The UI cannot always answer "what is the agent doing right now?"
- Operational status and durable transcript content are mixed together.
- It is hard to add richer streaming, clearer approvals, retries, persistent status lines, or future concurrency.
- Replay and live execution do not share a common event model.

The result is that Beaconhill has a coherent visual identity, but its interaction model is still shallow.

---

## Design Goals

The state model should achieve the following:

- Make the runtime's current phase explicit.
- Separate domain state from presentation state.
- Separate ephemeral operational events from durable conversation/session records.
- Give the UI one source of truth for what to render.
- Support current features without breaking the existing REPL model.
- Prepare the codebase for richer streaming, approvals, retries, replay, and eventual sub-agent or background execution support.

Non-goals:

- Replacing the terminal UI with a full-screen TUI.
- Redesigning the tool system itself.
- Replacing JSONL sessions.

---

## Core Idea

Beaconhill should be treated as a small state machine plus an event stream.

The runtime should:

1. own explicit state objects,
2. update them through well-defined transitions,
3. emit typed events,
4. let the UI render those events and state transitions.

This is better than the current pattern of interleaving runtime logic with ad hoc `print()` calls.

---

## State Model

Beaconhill's state should be split into distinct layers.

### 1. Application State

Application-level state describes what mode Beaconhill is in overall.

```python
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class AppMode(str, Enum):
    INTERACTIVE = "interactive"
    ONESHOT = "oneshot"
    REPLAY = "replay"


@dataclass
class AppState:
    mode: AppMode
    model: str
    host: str
    cwd: Path
    session_id: str
    session_path: Path
    resumed: bool = False
```

This state supports startup banner, session metadata, status line, and replay/live branching.

### 2. Turn State

Turn state describes the lifecycle of the current user request.

```python
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


@dataclass
class TurnState:
    turn_index: int
    user_input: str
    phase: TurnPhase = TurnPhase.STARTING
    retry_count: int = 0
    final_text: str | None = None
    error_text: str | None = None
```

This is the minimum useful state for a live request.

### 3. Tool Execution State

Tool execution needs its own state object because it is the most operationally important part of the experience.

```python
from typing import Any


class ToolStatus(str, Enum):
    REQUESTED = "requested"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    DENIED = "denied"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class ToolExecutionState:
    name: str
    arguments: dict[str, Any]
    status: ToolStatus = ToolStatus.REQUESTED
    output: str | None = None
    error_text: str | None = None
```

Turn state can point to the current tool:

```python
@dataclass
class TurnState:
    ...
    current_tool: ToolExecutionState | None = None
```

---

## Event Model

State alone is not enough. The runtime also needs typed events.

State answers:

- what is true now?

Events answer:

- what just happened?

### Starting Event Set

Start with only the events that the current UI actually needs to render. Expand when a concrete feature demands it.

```python
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
```

This covers the current rendering needs: pulse control, tool display, streaming, and turn boundaries.

### Event Shape

```python
@dataclass
class RuntimeEvent:
    type: EventType
    timestamp: str
    payload: dict[str, object] = field(default_factory=dict)
```

This event shape is intentionally simple. It is enough for the terminal UI, replay, logging, and future machine-readable telemetry if needed.

### Future Event Expansion

The following events are not needed yet but are natural additions when specific features require them:

- `SESSION_STARTED`, `SESSION_RESUMED` -- useful when startup becomes more complex or a status line needs session metadata.
- `CONTEXT_COMPACTION_STARTED`, `CONTEXT_COMPACTION_FINISHED` -- useful when compaction gets its own progress display.
- `TOOL_APPROVAL_REQUIRED`, `TOOL_APPROVED`, `TOOL_DENIED` -- useful when the approval UI becomes richer than a simple y/N prompt.
- `TURN_INTERRUPTED` -- useful when interrupt recovery becomes stateful.

Add these when a renderer or log consumer needs them, not before.

---

## Domain State vs Presentation State

This separation is the central design rule.

### Domain State

Domain state describes actual runtime facts:

- Beaconhill is in interactive mode.
- The current turn phase is `RUNNING_TOOL`.
- The current tool is `grep`.
- The last tool failed with a regex error.
- The final answer is currently streaming.

### Presentation State

Presentation state describes how those facts appear in the terminal:

- show pulse with label `running grep...`
- render approval tray
- open assistant response block
- print token count line at end of turn
- update status line with session/model/phase

The UI should not infer domain facts from ad hoc runtime behavior. It should receive explicit inputs and render deterministically.

---

## Durable vs Ephemeral Output

Beaconhill currently mixes these too freely.

### Durable Transcript Content

This should be treated as persistent conversational or operational record:

- user messages
- assistant final answers
- tool calls
- tool results
- permission outcomes

These belong in session history or a durable replay log.

### Ephemeral Operational Output

This should be treated as temporary execution affordance:

- pulses
- "thinking..."
- "retrying in 2s..."
- "compacting context..."
- transient progress updates

These should be renderable live without polluting durable transcript history.

### Rule

If a line exists primarily to help the user understand current execution progress, it should be an ephemeral event, not a durable transcript message.

This distinction matters for replay and trust. Users should be able to tell what the agent said from what the runtime was doing.

---

## Recommended Runtime State Machine

Below is the recommended high-level turn lifecycle.

```text
IDLE
  -> STARTING
  -> COMPACTING                (optional)
  -> CALLING_MODEL
  -> AWAITING_APPROVAL         (optional)
  -> RUNNING_TOOL              (0..n times)
  -> CALLING_MODEL             (repeat after tool result)
  -> STREAMING_FINAL
  -> COMPLETED

Error paths:
  -> ERROR
  -> INTERRUPTED
```

### Transition Examples

- `STARTING -> COMPACTING`
  Trigger: `needs_compaction(...)` is true

- `COMPACTING -> CALLING_MODEL`
  Trigger: compaction finishes

- `CALLING_MODEL -> AWAITING_APPROVAL`
  Trigger: assistant emitted tool call whose policy is `ASK`

- `CALLING_MODEL -> RUNNING_TOOL`
  Trigger: assistant emitted tool call whose policy is `ALLOW`

- `CALLING_MODEL -> STREAMING_FINAL`
  Trigger: assistant emitted no tool calls and final text generation begins

- `RUNNING_TOOL -> CALLING_MODEL`
  Trigger: tool finished and tool result was appended

- `STREAMING_FINAL -> COMPLETED`
  Trigger: stream ended cleanly

- `* -> ERROR`
  Trigger: runtime exception or transport failure

- `* -> INTERRUPTED`
  Trigger: keyboard interrupt

---

## File-Level Refactor Plan

### 1. Add a New State Module

Create:

- `src/beaconhill/state.py`

Responsibilities:

- enums for app mode, turn phase, tool status, event type
- dataclasses for `AppState`, `TurnState`, `ToolExecutionState`, `RuntimeEvent`

This module should contain no terminal rendering and no Ollama-specific logic. Export its public types from `src/beaconhill/__init__.py` so other modules can import directly from the package.

### 2. Add a New Runtime Coordination Module

Create:

- `src/beaconhill/runtime.py`

`runtime.py` is a **state machine that delegates execution**. It is not an executor that happens to track state.

Responsibilities:

- own the mutable `TurnState` and drive phase transitions
- emit `RuntimeEvent`s at transition boundaries
- delegate to the client for model calls, the registry for tool execution, and the session for persistence
- call `ui.py` functions at well-defined transition points

It should not contain model-calling logic, tool execution logic, or session serialization. Those stay in their existing modules.

`cli.py` should stop directly encoding the whole turn lifecycle.

### 3. Reduce `cli.py` to App Shell Responsibilities

`src/beaconhill/cli.py` should primarily:

- parse args
- load config
- initialize app/session/runtime
- read user input
- hand the turn to runtime orchestration
- delegate event rendering to `ui.py`

The current `_run_agentic_loop()` should either move or become a thin wrapper around `runtime.py`.

### 4. Keep `ui.py` as Named Render Functions

`src/beaconhill/ui.py` should continue to provide named functions (`tool_start`, `tool_end`, `permission_prompt`, etc.) rather than a single generic `render_event()` dispatcher.

Why: Beaconhill uses a scrolling-log model, not a full-screen TUI. In a scrolling log, targeted writes at the moment things happen are more natural than a single render pass driven by state. A generic `render_event(event, app_state, turn_state)` dispatcher would become a big match/switch that reconstructs what the caller already knew.

The key change is not how `ui.py` is structured internally. It is *who calls it and when*. Today, `cli.py` calls UI functions inline during orchestration. After this refactor, `runtime.py` calls them at well-defined state transitions. The UI functions themselves remain stable.

`ui.py` should not be responsible for inferring the agent's current state. It receives explicit inputs and renders deterministically.

### 5. Remove Direct UI Output From `client.py`

`src/beaconhill/client.py` should stop printing retry messages directly.

Instead, retries should be surfaced via:

- raised exceptions with context, or
- callback/event hooks provided by the caller

Example:

```python
def _call_with_retry(..., on_retry: Callable[[int, int, str], None] | None = None)
```

Then the runtime emits `MODEL_CALL_RETRYING` events.

The callback is a presentation-layer concern only. Retry *logic* (backoff strategy, max attempts) stays in `client.py`. The callback lets the runtime surface retries to the UI without the client knowing about terminal rendering.

### 6. Keep `session.py` Focused on Durable History

`src/beaconhill/session.py` should continue storing durable messages.

It should not absorb ephemeral pulse or retry events unless Beaconhill explicitly introduces a second structured event log.

If a second log is desired later, add a separate event log file rather than polluting message JSONL.

---

## Recommended UI Behaviors From State

### Startup

Render from `AppState`:

- mode
- model
- session id
- resumed/new state

### During Model Call

Render from `TurnPhase.CALLING_MODEL`:

- pulse on
- optional status line: `calling model`

### During Retry

Render from `MODEL_CALL_RETRYING`:

- transient info line
- persistent status line update with retry count

### During Approval

Render from `ToolExecutionState(status=APPROVAL_REQUIRED)`:

- approval tray
- stable formatting of tool name and arguments
- suspended pulse

### During Tool Execution

Render from `ToolExecutionState(status=RUNNING)`:

- pulse label `running <tool>`
- clear tray header

### During Final Streaming

Render from `TurnPhase.STREAMING_FINAL` plus `ASSISTANT_STREAM_CHUNK` events:

- start assistant response block once
- append chunks incrementally (the full streamed text is not accumulated in `TurnState` -- the session stores the final result)
- close cleanly on finish

### At Turn End

Render from `TurnPhase.COMPLETED`:

- token count
- optional elapsed time
- reset prompt state

---

## Replay Model

Replay should eventually render from durable structured records, not by reusing live `print()` behavior.

Recommended principle:

- live mode consumes both durable messages and ephemeral runtime events
- replay mode consumes durable transcript records only

This avoids replaying pulse artifacts and temporary retry lines that do not belong in history.

If Beaconhill later adds an optional structured event log, replay can offer:

- clean replay: messages only
- diagnostic replay: messages plus runtime events

---

## Migration Strategy

This should be implemented incrementally.

### Phase 1: Introduce State Types

Add `state.py` with enums and dataclasses only.

No behavior changes yet.

### Phase 2: Wrap Turn Execution With State Updates

Update the main loop so it constructs and mutates `TurnState`.

Continue using existing UI helpers, but derive calls from the explicit phase.

### Phase 3: Add Event Emission

Emit `RuntimeEvent`s from runtime orchestration.

At first, events can be consumed immediately by the same process.

### Phase 4: Move UI Calls Into Runtime Transition Points

Move scattered `ui.*` calls out of `cli.py` and into `runtime.py`, so each state transition has a single call site. The UI functions themselves (`tool_start`, `tool_end`, etc.) remain as named functions -- the change is *where* they are called, not *how* they are structured.

### Phase 5: Remove Client-Side Printing

Move retry/progress signaling out of `client.py`.

### Phase 6: Optional Enhancements

After the state/event model exists, add:

- persistent status line
- cleaner streaming blocks
- richer approval UIs
- diff-aware edit summaries
- optional event log

---

## Risks and Tradeoffs

### 1. More Abstraction

This adds structure and more types. For a very small CLI, that can feel heavier than necessary.

Response:

The current runtime is already complex enough to justify it. Streaming, retries, approvals, compaction, and replay are enough moving parts that implicit control flow is now the bigger risk.

### 2. Temporary Duplication

During migration, Beaconhill may briefly have both:

- old-style UI helper calls
- new event/state plumbing

Response:

That is acceptable if migration is staged deliberately.

### 3. Event Overdesign

Too many event types can create ceremony.

Response:

Start with a small event set and expand only when needed. The event list in this plan is an upper bound, not a required initial implementation.

---

## Recommendation

Beaconhill should adopt explicit state modeling now, before more UI features are added.

The current UI is already branded and readable. The real limitation is not styling. It is that the runtime does not expose its execution state as first-class data.

Start with the minimal viable implementation defined at the top of this document. That delivers the structural benefit without an architecture rewrite. Expand the event taxonomy and add richer UI components only when concrete features demand them.
