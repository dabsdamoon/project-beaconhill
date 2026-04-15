from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
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
    max_iterations: int = 5


def _persistent_failures(
    history: list[EvaluationResult], step_id: int
) -> list[str]:
    """Return issues that appeared in the last TWO evaluations for this step.

    Returning a non-empty list means the same failure survived one retry cycle,
    which is the pivot trigger: refinement isn't working; the generator should
    discard its current approach and try a fundamentally different one.
    """
    if len(history) < 2:
        return []
    last = next(
        (v for v in history[-1].verdicts if v.step_id == step_id and not v.passed),
        None,
    )
    prev = next(
        (v for v in history[-2].verdicts if v.step_id == step_id and not v.passed),
        None,
    )
    if last is None or prev is None:
        return []
    last_set = set(last.issues)
    prev_set = set(prev.issues)
    return sorted(last_set & prev_set)


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
    max_eval_iterations: int = 5,
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
            feedback=result,
            evaluation_history=state.evaluation_results,
            on_event=on_event, state=state,
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
    evaluation_history: list[EvaluationResult] | None = None,
) -> None:
    state.phase = OrchestratorPhase.GENERATING
    for step in steps:
        step.status = StepStatus.IN_PROGRESS
        session.update_plan(plan)
        _emit(on_event, EventType.STEP_STARTED, step_id=step.id, description=step.description)

        persistent = (
            _persistent_failures(evaluation_history, step.id)
            if evaluation_history else []
        )
        if persistent:
            removed = _delete_step_artifacts(step)
            _emit(
                on_event,
                EventType.PIVOT_TRIGGERED,
                step_id=step.id,
                persistent_issues=persistent,
                removed_files=removed,
            )
            if removed:
                ui.info(f"Pivot on step {step.id}: removed {len(removed)} prior file(s)")
        step_prompt = _build_step_prompt(
            step, plan, feedback=feedback, persistent_issues=persistent
        )
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
    step: PlanStep,
    plan: Plan,
    feedback: EvaluationResult | None = None,
    persistent_issues: list[str] | None = None,
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

    if persistent_issues:
        lines.append("## Pivot required")
        lines.append(
            "The following issues have survived at least one retry -- refining your "
            "previous approach is not working. DISCARD the current implementation "
            "and try a fundamentally different approach. Do not patch what is there; "
            "rewrite from scratch."
        )
        lines.append("")
        lines.append("Persistent issues:")
        for issue in persistent_issues:
            lines.append(f"  - {issue}")
        lines.append("")
    elif feedback is not None:
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


def _delete_step_artifacts(step: PlanStep) -> list[str]:
    """Remove the files this step claimed to produce, so the next attempt starts clean.

    Returns the list of paths actually removed. Missing files are silently skipped.
    Only deletes files (never directories) and never recurses. Paths are interpreted
    relative to the current working directory, which is the workspace.
    """
    removed: list[str] = []
    for f in step.files:
        path = Path(f)
        if path.exists() and path.is_file():
            try:
                path.unlink()
                removed.append(str(path))
            except OSError:
                pass
    return removed


def _emit(on_event: EventSink | None, event_type: EventType, **payload: object) -> None:
    if on_event is None:
        return
    on_event(RuntimeEvent(type=event_type, payload=payload))
