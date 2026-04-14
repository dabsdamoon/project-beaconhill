from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class StepStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


@dataclass
class PlanStep:
    id: int
    description: str
    acceptance_criteria: list[str]
    files: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "acceptance_criteria": self.acceptance_criteria,
            "files": self.files,
            "status": str(self.status),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlanStep:
        return cls(
            id=d["id"],
            description=d["description"],
            acceptance_criteria=d["acceptance_criteria"],
            files=d.get("files", []),
            status=StepStatus(d.get("status", "pending")),
        )


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "_plan": True,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "approved": self.approved,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Plan:
        return cls(
            goal=d["goal"],
            steps=[PlanStep.from_dict(s) for s in d["steps"]],
            created_at=d.get("created_at", ""),
            approved=d.get("approved", False),
        )

    def to_prompt(self) -> str:
        """Render plan as text for LLM consumption."""
        lines = [f"## Plan: {self.goal}", ""]
        for step in self.steps:
            status = f" [{step.status}]" if step.status != StepStatus.PENDING else ""
            lines.append(f"### Step {step.id}: {step.description}{status}")
            if step.files:
                lines.append(f"Files: {', '.join(step.files)}")
            lines.append("Acceptance criteria:")
            for criterion in step.acceptance_criteria:
                lines.append(f"  - {criterion}")
            lines.append("")
        return "\n".join(lines)

    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def failed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    def all_done(self) -> bool:
        return all(s.status == StepStatus.DONE for s in self.steps)


@dataclass
class StepVerdict:
    step_id: int
    passed: bool
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "passed": self.passed,
            "issues": self.issues,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StepVerdict:
        return cls(
            step_id=d["step_id"],
            passed=d["passed"],
            issues=d.get("issues", []),
        )


@dataclass
class EvaluationResult:
    overall_passed: bool
    verdicts: list[StepVerdict]
    summary: str
    iteration: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "_evaluation": True,
            "overall_passed": self.overall_passed,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "summary": self.summary,
            "iteration": self.iteration,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvaluationResult:
        return cls(
            overall_passed=d["overall_passed"],
            verdicts=[StepVerdict.from_dict(v) for v in d["verdicts"]],
            summary=d["summary"],
            iteration=d.get("iteration", 0),
        )

    def failed_step_ids(self) -> list[int]:
        return [v.step_id for v in self.verdicts if not v.passed]
