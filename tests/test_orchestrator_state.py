"""Tests for orchestrator state and session plan/evaluation persistence."""
import json
from pathlib import Path

from beaconhill.orchestrator import OrchestratorPhase, OrchestratorState
from beaconhill.plan import (
    EvaluationResult,
    Plan,
    PlanStep,
    StepStatus,
    StepVerdict,
)
from beaconhill.session import Session


class TestOrchestratorState:
    def test_defaults(self):
        state = OrchestratorState()
        assert state.phase == OrchestratorPhase.PLANNING
        assert state.plan is None
        assert state.evaluation_results == []
        assert state.current_iteration == 0
        assert state.max_iterations == 5

    def test_phase_values(self):
        assert OrchestratorPhase.PLANNING == "planning"
        assert OrchestratorPhase.GENERATING == "generating"
        assert OrchestratorPhase.EVALUATING == "evaluating"
        assert OrchestratorPhase.COMPLETE == "complete"
        assert OrchestratorPhase.FAILED == "failed"


class TestSessionPlanPersistence:
    def _make_plan(self) -> Plan:
        return Plan(
            goal="Refactor auth",
            steps=[
                PlanStep(
                    id=1,
                    description="Extract token logic",
                    acceptance_criteria=["token.py exists"],
                    files=["src/token.py"],
                ),
            ],
            created_at="2026-04-13T00:00:00+00:00",
        )

    def _make_eval(self) -> EvaluationResult:
        return EvaluationResult(
            overall_passed=True,
            verdicts=[StepVerdict(step_id=1, passed=True)],
            summary="All steps passed.",
            iteration=1,
        )

    def test_set_plan_persists_to_jsonl(self, tmp_path: Path):
        session = Session(model="test", session_dir=tmp_path)
        plan = self._make_plan()
        session.set_plan(plan)

        assert session.plan is plan

        lines = session.path.read_text().strip().split("\n")
        plan_line = json.loads(lines[-1])
        assert plan_line["_plan"] is True
        assert plan_line["goal"] == "Refactor auth"

    def test_update_plan_writes_new_line(self, tmp_path: Path):
        session = Session(model="test", session_dir=tmp_path)
        plan = self._make_plan()
        session.set_plan(plan)

        plan.steps[0].status = StepStatus.DONE
        session.update_plan(plan)

        lines = session.path.read_text().strip().split("\n")
        plan_lines = [json.loads(l) for l in lines if json.loads(l).get("_plan")]
        assert len(plan_lines) == 2
        assert plan_lines[1]["steps"][0]["status"] == "done"

    def test_add_evaluation_persists(self, tmp_path: Path):
        session = Session(model="test", session_dir=tmp_path)
        result = self._make_eval()
        session.add_evaluation(result)

        assert len(session.evaluation_results) == 1

        lines = session.path.read_text().strip().split("\n")
        eval_line = json.loads(lines[-1])
        assert eval_line["_evaluation"] is True
        assert eval_line["overall_passed"] is True

    def test_load_restores_plan_and_evaluations(self, tmp_path: Path):
        session = Session(model="test", session_dir=tmp_path)
        plan = self._make_plan()
        session.set_plan(plan)
        session.add_evaluation(self._make_eval())

        loaded = Session.load(session.path)
        assert loaded.plan is not None
        assert loaded.plan.goal == "Refactor auth"
        assert len(loaded.evaluation_results) == 1
        assert loaded.evaluation_results[0].overall_passed is True

    def test_load_without_plan_is_none(self, tmp_path: Path):
        session = Session(model="test", session_dir=tmp_path)
        loaded = Session.load(session.path)
        assert loaded.plan is None
        assert loaded.evaluation_results == []

    def test_load_uses_latest_plan(self, tmp_path: Path):
        """When multiple plan lines exist, the last one wins."""
        session = Session(model="test", session_dir=tmp_path)
        plan = self._make_plan()
        session.set_plan(plan)

        plan.approved = True
        plan.steps[0].status = StepStatus.DONE
        session.update_plan(plan)

        loaded = Session.load(session.path)
        assert loaded.plan is not None
        assert loaded.plan.approved is True
        assert loaded.plan.steps[0].status == StepStatus.DONE

    def test_messages_not_affected_by_plan(self, tmp_path: Path):
        """Plan and evaluation lines don't pollute the message list."""
        from beaconhill.models import Message, Role

        session = Session(model="test", session_dir=tmp_path)
        session.append(Message(role=Role.USER, content="hello"))
        session.set_plan(self._make_plan())
        session.add_evaluation(self._make_eval())
        session.append(Message(role=Role.ASSISTANT, content="hi"))

        loaded = Session.load(session.path)
        assert len(loaded.messages) == 2
        assert loaded.messages[0].role == Role.USER
        assert loaded.messages[1].role == Role.ASSISTANT
        assert loaded.plan is not None
        assert len(loaded.evaluation_results) == 1
