from __future__ import annotations

import json

from beaconhill.client import LLMClient
from beaconhill.models import Message, Role
from beaconhill.plan import EvaluationResult, Plan, StepEvidence, StepVerdict
from beaconhill.planner import _extract_json_object
from beaconhill.prompts import EVALUATOR_SYSTEM_PROMPT, build_evaluator_user_prompt
from beaconhill.tools import Permission, Policy, ToolRegistry

MAX_EVALUATOR_ITERATIONS = 20


def create_evaluator_registry(base: ToolRegistry) -> ToolRegistry:
    """Return a registry sharing `base`'s tools but with read-only policies."""
    restricted = ToolRegistry(
        policies={
            Permission.READ: Policy.ALLOW,
            Permission.WRITE: Policy.DENY,
            Permission.EXECUTE: Policy.DENY,
        }
    )
    for spec in base.list_specs():
        restricted.register(spec)
    return restricted


def evaluate(
    client: LLMClient,
    plan: Plan,
    evidence: list[StepEvidence],
    base_registry: ToolRegistry,
    *,
    iteration: int = 0,
    max_iterations: int = MAX_EVALUATOR_ITERATIONS,
) -> EvaluationResult:
    """Independently verify whether the plan's acceptance criteria were met.

    Runs a tool-using loop with read-only access. On malformed output or
    exceeded iterations, returns a failing verdict with a descriptive summary
    so the orchestrator can decide how to proceed.
    """
    registry = create_evaluator_registry(base_registry)
    tools = registry.to_ollama()

    evidence_text = "\n\n".join(e.to_prompt() for e in evidence) or "(no evidence)"
    messages: list[Message] = [
        Message(role=Role.SYSTEM, content=EVALUATOR_SYSTEM_PROMPT),
        Message(
            role=Role.USER,
            content=build_evaluator_user_prompt(plan.to_prompt(), evidence_text),
        ),
    ]

    for _ in range(max_iterations):
        response = client.chat(messages, tools=tools)
        messages.append(response)

        if not response.tool_calls:
            parsed = _parse_evaluation(response.content or "", plan, iteration)
            if parsed is not None:
                return parsed
            return _fallback_failure(
                plan, iteration, "Evaluator output could not be parsed as JSON."
            )

        for tc in response.tool_calls:
            if registry.check_permission(tc.name) == Policy.DENY:
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=f"Permission denied: {tc.name} is unavailable to the evaluator (read-only).",
                        tool_call_id=tc.name,
                    )
                )
                continue
            result = registry.execute(tc.name, tc.arguments)
            messages.append(
                Message(role=Role.TOOL, content=result.output, tool_call_id=tc.name)
            )

    return _fallback_failure(
        plan, iteration, "Evaluator exceeded maximum tool iterations."
    )


def _parse_evaluation(text: str, plan: Plan, iteration: int) -> EvaluationResult | None:
    payload = _extract_json_object(text)
    if payload is None:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    raw_verdicts = data.get("verdicts")
    if not isinstance(raw_verdicts, list) or not raw_verdicts:
        return None

    verdicts: list[StepVerdict] = []
    valid_ids = {s.id for s in plan.steps}
    for raw in raw_verdicts:
        if not isinstance(raw, dict):
            return None
        step_id = raw.get("step_id")
        passed = raw.get("passed")
        if not isinstance(step_id, int) or not isinstance(passed, bool):
            return None
        if step_id not in valid_ids:
            continue
        issues_raw = raw.get("issues", [])
        issues = [str(i) for i in issues_raw] if isinstance(issues_raw, list) else []
        verdicts.append(StepVerdict(step_id=step_id, passed=passed, issues=issues))

    if not verdicts:
        return None

    overall = data.get("overall_passed")
    if not isinstance(overall, bool):
        overall = all(v.passed for v in verdicts)

    summary = data.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    return EvaluationResult(
        overall_passed=overall,
        verdicts=verdicts,
        summary=summary,
        iteration=iteration,
    )


def _fallback_failure(plan: Plan, iteration: int, reason: str) -> EvaluationResult:
    return EvaluationResult(
        overall_passed=False,
        verdicts=[
            StepVerdict(step_id=step.id, passed=False, issues=[reason])
            for step in plan.steps
        ],
        summary=reason,
        iteration=iteration,
    )


def collect_evidence(session_messages: list[Message], plan: Plan) -> list[StepEvidence]:
    """Scan session messages for step boundaries and summarize tool activity.

    The orchestrator marks each step by appending a user message that begins with
    `You are executing step N`. For each step we keep the *most recent* attempt's
    trace so a post-retry evaluation sees fresh evidence.
    """
    step_ids = {s.id for s in plan.steps}
    latest: dict[int, StepEvidence] = {}

    current: StepEvidence | None = None
    for msg in session_messages:
        if msg.role == Role.USER and msg.content:
            step_id = _detect_step_id(msg.content)
            if step_id is not None and step_id in step_ids:
                current = StepEvidence(step_id=step_id)
                latest[step_id] = current
                continue
        if current is None:
            continue
        if msg.role == Role.ASSISTANT:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    current.tool_calls.append(_summarize_tool_call(tc.name, tc.arguments))
                    path = tc.arguments.get("file_path")
                    if isinstance(path, str) and path not in current.files_touched:
                        current.files_touched.append(path)
            if msg.content:
                current.assistant_text = msg.content

    return [latest[sid] for sid in sorted(latest)]


def _detect_step_id(text: str) -> int | None:
    prefix = "You are executing step "
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix):]
    num = ""
    for ch in rest:
        if ch.isdigit():
            num += ch
        else:
            break
    return int(num) if num else None


def _summarize_tool_call(name: str, arguments: dict) -> str:
    if "file_path" in arguments:
        return f"{name}({arguments['file_path']})"
    if "command" in arguments:
        cmd = str(arguments["command"])
        if len(cmd) > 60:
            cmd = cmd[:60] + "..."
        return f"{name}({cmd})"
    if "pattern" in arguments:
        return f"{name}({arguments['pattern']})"
    return f"{name}(...)"
