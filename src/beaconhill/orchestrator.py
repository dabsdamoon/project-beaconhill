from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from beaconhill import ui
from beaconhill.client import OllamaClient
from beaconhill.evaluator import collect_evidence, evaluate
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
    max_eval_iterations: int = 3,
    evaluator_tools: list[str] | None = None,
    skip_evaluation: bool = False,
    on_event: EventSink | None = None,
) -> OrchestratorState:
    """Plan -> (approve) -> per-step generate -> evaluate -> (retry failed steps).

    The evaluator verifies acceptance criteria independently with read-only tools.
    On failure, failed steps are re-generated with evaluator issues as feedback,
    up to `max_eval_iterations` cycles.
    """
    state = OrchestratorState(
        phase=OrchestratorPhase.PLANNING, max_iterations=max_eval_iterations
    )

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
        # "edit" is treated as approval for now.

    plan.approved = True
    session.update_plan(plan)
    _emit(on_event, EventType.PLAN_APPROVED, plan_goal=plan.goal)

    # Run all steps at least once.
    _generate_steps(
        plan.steps, plan, client, registry, session, tools,
        allow_all, context_limit, generator_max_iterations,
        feedback=None, on_event=on_event, state=state,
    )

    if skip_evaluation:
        state.phase = OrchestratorPhase.COMPLETE
        return state

    # Evaluate -> retry failed steps up to max_eval_iterations.
    for iteration in range(1, max_eval_iterations + 1):
        state.phase = OrchestratorPhase.EVALUATING
        state.current_iteration = iteration
        _emit(on_event, EventType.EVALUATION_STARTED, iteration=iteration)

        evidence = collect_evidence(session.messages, plan)
        result = evaluate(
            client,
            plan,
            evidence,
            registry,
            allowed_tools=evaluator_tools,
            iteration=iteration,
        )
        state.evaluation_results.append(result)
        session.add_evaluation(result)
        _emit(
            on_event,
            EventType.EVALUATION_COMPLETED,
            iteration=iteration,
            passed=result.overall_passed,
            failed_ids=result.failed_step_ids(),
        )

        if result.overall_passed:
            state.phase = OrchestratorPhase.COMPLETE
            return state

        if iteration == max_eval_iterations:
            state.phase = OrchestratorPhase.FAILED
            return state

        failed_ids = set(result.failed_step_ids())
        failed_steps = [s for s in plan.steps if s.id in failed_ids]
        for step in failed_steps:
            step.status = StepStatus.PENDING
        session.update_plan(plan)
        _emit(on_event, EventType.ORCHESTRATOR_RETRY, iteration=iteration, failed_ids=sorted(failed_ids))

        state.phase = OrchestratorPhase.GENERATING
        _generate_steps(
            failed_steps, plan, client, registry, session, tools,
            allow_all, context_limit, generator_max_iterations,
            feedback=result, on_event=on_event, state=state,
        )

    state.phase = OrchestratorPhase.FAILED
    return state


def _generate_steps(
    steps: list[PlanStep],
    plan: Plan,
    client: OllamaClient,
    registry: "ToolRegistry",
    session: Session,
    tools: list[dict[str, Any]],
    allow_all: bool,
    context_limit: int,
    generator_max_iterations: int,
    feedback: EvaluationResult | None,
    on_event: EventSink | None,
    state: OrchestratorState,
) -> None:
    state.phase = OrchestratorPhase.GENERATING
    for step in steps:
        step.status = StepStatus.IN_PROGRESS
        session.update_plan(plan)
        _emit(on_event, EventType.STEP_STARTED, step_id=step.id, description=step.description)

        step_prompt = _build_step_prompt(step, plan, feedback=feedback)
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


def _build_step_prompt(
    step: PlanStep, plan: Plan, feedback: EvaluationResult | None = None
) -> str:
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

    if feedback is not None:
        verdict = next(
            (v for v in feedback.verdicts if v.step_id == step.id and not v.passed),
            None,
        )
        if verdict is not None:
            lines.append("## Evaluator feedback from the previous attempt")
            lines.append("Your previous work did not meet these criteria. Fix the following:")
            for issue in verdict.issues:
                lines.append(f"  - {issue}")
            lines.append("")

    lines.append(
        "Complete this step now. Stay within its scope -- do not work on other steps."
    )
    return "\n".join(lines)


def _emit(on_event: EventSink | None, event_type: EventType, **payload: object) -> None:
    if on_event is None:
        return
    on_event(RuntimeEvent(type=event_type, payload=payload))
