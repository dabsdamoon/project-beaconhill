from __future__ import annotations

import json
import re

from beaconhill.client import LLMClient
from beaconhill.models import Message, Role
from beaconhill.plan import Plan, PlanStep
from beaconhill.prompts import PLANNER_SYSTEM_PROMPT, build_planner_user_prompt


def create_plan(
    client: LLMClient,
    user_input: str,
    project_context: str = "",
) -> Plan:
    """Generate a structured Plan from a user request.

    Falls back to a single-step plan wrapping the user's request if the
    model output cannot be parsed as valid JSON matching the Plan schema.
    """
    messages = [
        Message(role=Role.SYSTEM, content=PLANNER_SYSTEM_PROMPT),
        Message(
            role=Role.USER,
            content=build_planner_user_prompt(user_input, project_context),
        ),
    ]

    response = client.chat(messages)
    text = response.content or ""

    plan = _parse_plan(text)
    if plan is not None:
        return plan

    return _fallback_plan(user_input)


def _parse_plan(text: str) -> Plan | None:
    payload = _extract_json_object(text)
    if payload is None:
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    goal = data.get("goal")
    raw_steps = data.get("steps")
    if not isinstance(goal, str) or not isinstance(raw_steps, list) or not raw_steps:
        return None

    steps: list[PlanStep] = []
    for i, raw in enumerate(raw_steps, start=1):
        if not isinstance(raw, dict):
            return None
        description = raw.get("description")
        criteria = raw.get("acceptance_criteria")
        if not isinstance(description, str) or not isinstance(criteria, list):
            return None
        files = raw.get("files", [])
        if not isinstance(files, list):
            files = []
        steps.append(
            PlanStep(
                id=raw.get("id", i) if isinstance(raw.get("id"), int) else i,
                description=description,
                acceptance_criteria=[str(c) for c in criteria],
                files=[str(f) for f in files],
            )
        )

    return Plan(goal=goal, steps=steps)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json_object(text: str) -> str | None:
    """Pull a JSON object out of free-form model output.

    Handles bare JSON, fenced code blocks, and text surrounding the object.
    """
    text = text.strip()
    if not text:
        return None

    fenced = _FENCE_RE.search(text)
    if fenced:
        candidate = fenced.group(1).strip()
        if candidate.startswith("{"):
            return candidate

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return None


def _fallback_plan(user_input: str) -> Plan:
    return Plan(
        goal=user_input.strip() or "Execute user request",
        steps=[
            PlanStep(
                id=1,
                description=user_input.strip() or "Execute user request",
                acceptance_criteria=["User's request is addressed."],
                files=[],
            )
        ],
    )
