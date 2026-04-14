from __future__ import annotations

import enum
from dataclasses import dataclass, field

from beaconhill.plan import EvaluationResult, Plan


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
