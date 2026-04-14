"""Tests for plan data models: Plan, PlanStep, StepVerdict, EvaluationResult."""
from beaconhill.plan import (
    EvaluationResult,
    Plan,
    PlanStep,
    StepStatus,
    StepVerdict,
)


class TestPlanStep:
    def test_to_dict_roundtrip(self):
        step = PlanStep(
            id=1,
            description="Create utils module",
            acceptance_criteria=["file exists", "has parse function"],
            files=["src/utils.py"],
            status=StepStatus.DONE,
        )
        d = step.to_dict()
        restored = PlanStep.from_dict(d)
        assert restored.id == 1
        assert restored.description == "Create utils module"
        assert restored.acceptance_criteria == ["file exists", "has parse function"]
        assert restored.files == ["src/utils.py"]
        assert restored.status == StepStatus.DONE

    def test_defaults(self):
        step = PlanStep(id=1, description="x", acceptance_criteria=["y"])
        assert step.files == []
        assert step.status == StepStatus.PENDING

    def test_from_dict_missing_optional_fields(self):
        d = {"id": 2, "description": "d", "acceptance_criteria": ["c"]}
        step = PlanStep.from_dict(d)
        assert step.files == []
        assert step.status == StepStatus.PENDING


class TestPlan:
    def _make_plan(self) -> Plan:
        return Plan(
            goal="Add logging",
            steps=[
                PlanStep(
                    id=1,
                    description="Create logger",
                    acceptance_criteria=["logger.py exists"],
                    files=["src/logger.py"],
                ),
                PlanStep(
                    id=2,
                    description="Integrate logger",
                    acceptance_criteria=["main.py imports logger"],
                    files=["src/main.py"],
                ),
            ],
            created_at="2026-04-13T00:00:00+00:00",
        )

    def test_to_dict_has_plan_marker(self):
        plan = self._make_plan()
        d = plan.to_dict()
        assert d["_plan"] is True
        assert d["goal"] == "Add logging"
        assert len(d["steps"]) == 2

    def test_roundtrip(self):
        plan = self._make_plan()
        d = plan.to_dict()
        restored = Plan.from_dict(d)
        assert restored.goal == plan.goal
        assert len(restored.steps) == 2
        assert restored.steps[0].description == "Create logger"
        assert restored.approved is False

    def test_to_prompt_contains_steps(self):
        plan = self._make_plan()
        text = plan.to_prompt()
        assert "## Plan: Add logging" in text
        assert "### Step 1: Create logger" in text
        assert "### Step 2: Integrate logger" in text
        assert "logger.py exists" in text
        assert "Files: src/logger.py" in text

    def test_to_prompt_shows_status(self):
        plan = self._make_plan()
        plan.steps[0].status = StepStatus.DONE
        text = plan.to_prompt()
        assert "[done]" in text

    def test_pending_steps(self):
        plan = self._make_plan()
        plan.steps[0].status = StepStatus.DONE
        pending = plan.pending_steps()
        assert len(pending) == 1
        assert pending[0].id == 2

    def test_failed_steps(self):
        plan = self._make_plan()
        plan.steps[1].status = StepStatus.FAILED
        failed = plan.failed_steps()
        assert len(failed) == 1
        assert failed[0].id == 2

    def test_all_done(self):
        plan = self._make_plan()
        assert plan.all_done() is False
        plan.steps[0].status = StepStatus.DONE
        plan.steps[1].status = StepStatus.DONE
        assert plan.all_done() is True

    def test_approved_flag_persists(self):
        plan = self._make_plan()
        plan.approved = True
        d = plan.to_dict()
        restored = Plan.from_dict(d)
        assert restored.approved is True


class TestStepVerdict:
    def test_roundtrip(self):
        v = StepVerdict(step_id=1, passed=False, issues=["file missing"])
        d = v.to_dict()
        restored = StepVerdict.from_dict(d)
        assert restored.step_id == 1
        assert restored.passed is False
        assert restored.issues == ["file missing"]

    def test_defaults(self):
        v = StepVerdict(step_id=1, passed=True)
        assert v.issues == []


class TestEvaluationResult:
    def test_roundtrip(self):
        result = EvaluationResult(
            overall_passed=False,
            verdicts=[
                StepVerdict(step_id=1, passed=True),
                StepVerdict(step_id=2, passed=False, issues=["missing import"]),
            ],
            summary="Step 2 failed.",
            iteration=1,
        )
        d = result.to_dict()
        assert d["_evaluation"] is True

        restored = EvaluationResult.from_dict(d)
        assert restored.overall_passed is False
        assert len(restored.verdicts) == 2
        assert restored.verdicts[1].issues == ["missing import"]
        assert restored.summary == "Step 2 failed."
        assert restored.iteration == 1

    def test_failed_step_ids(self):
        result = EvaluationResult(
            overall_passed=False,
            verdicts=[
                StepVerdict(step_id=1, passed=True),
                StepVerdict(step_id=2, passed=False, issues=["x"]),
                StepVerdict(step_id=3, passed=False, issues=["y"]),
            ],
            summary="",
        )
        assert result.failed_step_ids() == [2, 3]
