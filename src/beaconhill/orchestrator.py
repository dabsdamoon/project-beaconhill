from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from beaconhill import ui
from beaconhill.client import OllamaClient
from beaconhill.models import Message, Role
from beaconhill.plan import EvaluationResult, Plan, PlanStep, StepStatus
from beaconhill.planner import create_plan
from beaconhill.runtime import EventSink, run_agentic_loop
from beaconhill.session import Session
from beaconhill.state import EventType, RuntimeEvent

if TYPE_CHECKING:
    from beaconhill.tools import ToolRegistry


class OrchestratorPhase(enum.StrEnum):
    PLANNING = "planning"
    PLAN_APPROVAL = "plan_approval"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class OrchestratorState:
    phase: OrchestratorPhase = OrchestratorPhase.PLANNING
    plan: Plan | None = None
    evaluation_results: list[EvaluationResult] = field(default_factory=list)
    current_iteration: int = 0
    max_iterations: int = 3


def run_orchestrated(
    client: OllamaClient,
    registry: "ToolRegistry",
    session: Session,
    tools: list[dict[str, Any]],
    allow_all: bool,
    context_limit: int,
    user_input: str,
    *,
    interactive: bool = True,
    project_context: str = "",
    generator_max_iterations: int = 50,
    on_event: EventSink | None = None,
) -> OrchestratorState:
    """Plan -> (approve) -> per-step generate. No evaluator yet (Phase 3)."""
    state = OrchestratorState(phase=OrchestratorPhase.PLANNING)

    plan = create_plan(client, user_input, project_context)
    state.plan = plan
    session.set_plan(plan)
    _emit(on_event, EventType.PLAN_CREATED, plan_goal=plan.goal, step_count=len(plan.steps))

    if interactive and len(plan.steps) > 1:
        state.phase = OrchestratorPhase.PLAN_APPROVAL
        ui.display_plan(plan)
        approval = ui.plan_approval_prompt()
        if approval == "reject":
            state.phase = OrchestratorPhase.FAILED
            return state
        # Phase 2 treats "edit" as approval; Phase 3+ will implement editing.

    plan.approved = True
    session.update_plan(plan)
    _emit(on_event, EventType.PLAN_APPROVED, plan_goal=plan.goal)

    state.phase = OrchestratorPhase.GENERATING
    for step in plan.steps:
        step.status = StepStatus.IN_PROGRESS
        session.update_plan(plan)
        _emit(on_event, EventType.STEP_STARTED, step_id=step.id, description=step.description)

        step_prompt = _build_step_prompt(step, plan)
        session.append(Message(role=Role.USER, content=step_prompt))

        try:
            run_agentic_loop(
                client=client,
                registry=registry,
                session=session,
                tools=tools,
                allow_all=allow_all,
                context_limit=context_limit,
                max_iterations=generator_max_iterations,
                on_event=on_event,
            )
        except Exception:
            step.status = StepStatus.FAILED
            session.update_plan(plan)
            state.phase = OrchestratorPhase.FAILED
            raise

        step.status = StepStatus.DONE
        session.update_plan(plan)
        _emit(on_event, EventType.STEP_COMPLETED, step_id=step.id)

    state.phase = OrchestratorPhase.COMPLETE
    return state


def _build_step_prompt(step: PlanStep, plan: Plan) -> str:
    lines = [
        f"You are executing step {step.id} of the plan: \"{plan.goal}\".",
        "",
        f"## Step {step.id}: {step.description}",
    ]
    if step.files:
        lines.append(f"Files likely involved: {', '.join(step.files)}")
    lines.append("")
    lines.append("Acceptance criteria:")
    for c in step.acceptance_criteria:
        lines.append(f"  - {c}")
    lines.append("")
    lines.append(
        "Complete this step now. Stay within its scope -- do not work on other steps."
    )
    return "\n".join(lines)


def _emit(on_event: EventSink | None, event_type: EventType, **payload: object) -> None:
    if on_event is None:
        return
    on_event(RuntimeEvent(type=event_type, payload=payload))
