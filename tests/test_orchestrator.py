"""Integration tests for run_orchestrated: plan -> approval -> per-step generate."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from beaconhill.models import Message, Role
from beaconhill.orchestrator import (
    OrchestratorPhase,
    _persistent_failures,
    run_orchestrated,
)
from beaconhill.plan import (
    EvaluationResult,
    Plan,
    PlanStep,
    StepStatus,
    StepVerdict,
)
from beaconhill.session import Session
from beaconhill.state import EventType, RuntimeEvent


def _plan_json(goal: str, steps: list[dict]) -> str:
    return json.dumps({"goal": goal, "steps": steps})


def _mock_client_with_plan(plan_payload: str) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = Message(role=Role.ASSISTANT, content=plan_payload)
    return client


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session(model="test", session_dir=tmp_path)


class TestRunOrchestratedHappyPath:
    def test_single_step_plan_skips_approval(self, session: Session):
        payload = _plan_json(
            "Add greet",
            [
                {
                    "id": 1,
                    "description": "Create greet.py",
                    "acceptance_criteria": ["greet.py exists"],
                    "files": ["greet.py"],
                }
            ],
        )
        client = _mock_client_with_plan(payload)
        registry = MagicMock()

        with patch("beaconhill.orchestrator.run_agentic_loop") as mock_loop:
            state = run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="Add a greet function",
                interactive=True,
                skip_evaluation=True,
            )

        assert state.phase == OrchestratorPhase.COMPLETE
        assert state.plan is not None
        assert state.plan.approved is True
        assert state.plan.steps[0].status == StepStatus.DONE
        assert mock_loop.call_count == 1

    def test_multi_step_interactive_requires_approval(self, session: Session):
        payload = _plan_json(
            "x",
            [
                {"id": 1, "description": "a", "acceptance_criteria": ["c"]},
                {"id": 2, "description": "b", "acceptance_criteria": ["c"]},
            ],
        )
        client = _mock_client_with_plan(payload)
        registry = MagicMock()

        with patch("beaconhill.orchestrator.run_agentic_loop") as mock_loop, patch(
            "beaconhill.orchestrator.ui"
        ) as mock_ui:
            mock_ui.plan_approval_prompt.return_value = "approve"
            state = run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do two things",
                interactive=True,
                skip_evaluation=True,
            )

        assert state.phase == OrchestratorPhase.COMPLETE
        assert mock_ui.display_plan.called
        assert mock_ui.plan_approval_prompt.called
        assert mock_loop.call_count == 2

    def test_multi_step_non_interactive_skips_approval(self, session: Session):
        payload = _plan_json(
            "x",
            [
                {"id": 1, "description": "a", "acceptance_criteria": ["c"]},
                {"id": 2, "description": "b", "acceptance_criteria": ["c"]},
            ],
        )
        client = _mock_client_with_plan(payload)
        registry = MagicMock()

        with patch("beaconhill.orchestrator.run_agentic_loop") as mock_loop, patch(
            "beaconhill.orchestrator.ui"
        ) as mock_ui:
            state = run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do two things",
                interactive=False,
                skip_evaluation=True,
            )

        assert state.phase == OrchestratorPhase.COMPLETE
        assert not mock_ui.plan_approval_prompt.called
        assert mock_loop.call_count == 2


class TestRunOrchestratedRejection:
    def test_reject_halts_without_running_generator(self, session: Session):
        payload = _plan_json(
            "x",
            [
                {"id": 1, "description": "a", "acceptance_criteria": ["c"]},
                {"id": 2, "description": "b", "acceptance_criteria": ["c"]},
            ],
        )
        client = _mock_client_with_plan(payload)
        registry = MagicMock()

        with patch("beaconhill.orchestrator.run_agentic_loop") as mock_loop, patch(
            "beaconhill.orchestrator.ui"
        ) as mock_ui:
            mock_ui.plan_approval_prompt.return_value = "reject"
            state = run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do two things",
                interactive=True,
                skip_evaluation=True,
            )

        assert state.phase == OrchestratorPhase.FAILED
        assert state.plan is not None
        assert state.plan.approved is False
        assert not mock_loop.called


class TestEventEmission:
    def test_emits_plan_step_events(self, session: Session):
        payload = _plan_json(
            "x",
            [{"id": 1, "description": "a", "acceptance_criteria": ["c"]}],
        )
        client = _mock_client_with_plan(payload)
        registry = MagicMock()

        events: list[RuntimeEvent] = []

        with patch("beaconhill.orchestrator.run_agentic_loop"):
            run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do it",
                interactive=False,
                on_event=events.append,
                skip_evaluation=True,
            )

        types = [e.type for e in events]
        assert EventType.PLAN_CREATED in types
        assert EventType.PLAN_APPROVED in types
        assert EventType.STEP_STARTED in types
        assert EventType.STEP_COMPLETED in types


class TestStepFailure:
    def test_generator_exception_marks_step_failed(self, session: Session):
        payload = _plan_json(
            "x",
            [{"id": 1, "description": "a", "acceptance_criteria": ["c"]}],
        )
        client = _mock_client_with_plan(payload)
        registry = MagicMock()

        with patch(
            "beaconhill.orchestrator.run_agentic_loop",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                run_orchestrated(
                    client=client,
                    registry=registry,
                    session=session,
                    tools=[],
                    allow_all=True,
                    context_limit=4096,
                    user_input="do it",
                    interactive=False,
                    skip_evaluation=True,
                )

        assert session.plan is not None
        assert session.plan.steps[0].status == StepStatus.FAILED


class TestPersistentFailures:
    def _eval(self, step_id: int, passed: bool, issues: list[str]) -> EvaluationResult:
        return EvaluationResult(
            overall_passed=passed,
            verdicts=[StepVerdict(step_id=step_id, passed=passed, issues=issues)],
            summary="",
        )

    def test_returns_empty_with_one_evaluation(self):
        hist = [self._eval(1, False, ["x"])]
        assert _persistent_failures(hist, 1) == []

    def test_returns_empty_when_no_overlap(self):
        hist = [
            self._eval(1, False, ["missing_button"]),
            self._eval(1, False, ["wrong_color"]),
        ]
        assert _persistent_failures(hist, 1) == []

    def test_returns_overlap(self):
        hist = [
            self._eval(1, False, ["missing_button", "wrong_color"]),
            self._eval(1, False, ["wrong_color", "bad_radius"]),
        ]
        assert _persistent_failures(hist, 1) == ["wrong_color"]

    def test_returns_empty_when_step_now_passes(self):
        hist = [
            self._eval(1, False, ["x"]),
            self._eval(1, True, []),
        ]
        assert _persistent_failures(hist, 1) == []

    def test_returns_empty_when_step_missing_in_prev(self):
        # step 1 wasn't evaluated in prev iteration
        hist = [
            EvaluationResult(
                overall_passed=True, verdicts=[], summary=""
            ),
            self._eval(1, False, ["x"]),
        ]
        assert _persistent_failures(hist, 1) == []


class TestOrchestratorPivotFlow:
    def _plan_payload(self) -> str:
        return json.dumps(
            {
                "goal": "g",
                "steps": [{"id": 1, "description": "a", "acceptance_criteria": ["c"]}],
            }
        )

    def test_pivot_prompt_emitted_after_two_same_failures(self, tmp_path: Path):
        plan_payload = self._plan_payload()
        fail_eval = json.dumps(
            {
                "overall_passed": False,
                "verdicts": [{"step_id": 1, "passed": False, "issues": ["missing_foo"]}],
                "summary": "still missing",
            }
        )
        pass_eval = json.dumps(
            {
                "overall_passed": True,
                "verdicts": [{"step_id": 1, "passed": True, "issues": []}],
                "summary": "ok",
            }
        )
        client = MagicMock()
        client.chat.side_effect = [
            Message(role=Role.ASSISTANT, content=plan_payload),
            Message(role=Role.ASSISTANT, content=fail_eval),
            Message(role=Role.ASSISTANT, content=fail_eval),
            Message(role=Role.ASSISTANT, content=pass_eval),
        ]
        registry = MagicMock()
        session = Session(model="test", session_dir=tmp_path)

        with patch("beaconhill.orchestrator.run_agentic_loop"):
            state = run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do it",
                interactive=False,
                max_eval_iterations=5,
            )

        assert state.phase == OrchestratorPhase.COMPLETE
        user_prompts = [m.content for m in session.messages if m.role == Role.USER]
        # 3 step prompts: first, retry-with-feedback, retry-with-pivot
        assert len(user_prompts) == 3
        assert "Pivot required" not in user_prompts[0]
        assert "Pivot required" not in user_prompts[1]
        assert "Pivot required" in user_prompts[2]
        assert "missing_foo" in user_prompts[2]
        assert "DISCARD" in user_prompts[2]

    def test_no_pivot_when_failures_differ(self, tmp_path: Path):
        plan_payload = self._plan_payload()
        fail_a = json.dumps(
            {
                "overall_passed": False,
                "verdicts": [{"step_id": 1, "passed": False, "issues": ["a"]}],
                "summary": "",
            }
        )
        fail_b = json.dumps(
            {
                "overall_passed": False,
                "verdicts": [{"step_id": 1, "passed": False, "issues": ["b"]}],
                "summary": "",
            }
        )
        pass_eval = json.dumps(
            {
                "overall_passed": True,
                "verdicts": [{"step_id": 1, "passed": True, "issues": []}],
                "summary": "ok",
            }
        )
        client = MagicMock()
        client.chat.side_effect = [
            Message(role=Role.ASSISTANT, content=plan_payload),
            Message(role=Role.ASSISTANT, content=fail_a),
            Message(role=Role.ASSISTANT, content=fail_b),
            Message(role=Role.ASSISTANT, content=pass_eval),
        ]
        registry = MagicMock()
        session = Session(model="test", session_dir=tmp_path)

        with patch("beaconhill.orchestrator.run_agentic_loop"):
            run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do it",
                interactive=False,
                max_eval_iterations=5,
            )

        user_prompts = [m.content for m in session.messages if m.role == Role.USER]
        # Three prompts, none should pivot (different issues each time)
        assert all("Pivot required" not in p for p in user_prompts)


class TestSessionPersistence:
    def test_plan_persisted_to_jsonl(self, session: Session):
        payload = _plan_json(
            "persistence",
            [{"id": 1, "description": "a", "acceptance_criteria": ["c"]}],
        )
        client = _mock_client_with_plan(payload)
        registry = MagicMock()

        with patch("beaconhill.orchestrator.run_agentic_loop"):
            run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do it",
                interactive=False,
                skip_evaluation=True,
            )

        loaded = Session.load(session.path)
        assert loaded.plan is not None
        assert loaded.plan.goal == "persistence"
        assert loaded.plan.approved is True
        assert loaded.plan.steps[0].status == StepStatus.DONE

    def test_step_prompt_appended_as_user_message(self, session: Session):
        payload = _plan_json(
            "x",
            [
                {
                    "id": 1,
                    "description": "Create logger",
                    "acceptance_criteria": ["logger exists"],
                    "files": ["src/logger.py"],
                }
            ],
        )
        client = _mock_client_with_plan(payload)
        registry = MagicMock()

        with patch("beaconhill.orchestrator.run_agentic_loop"):
            run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do it",
                interactive=False,
                skip_evaluation=True,
            )

        user_msgs = [m for m in session.messages if m.role == Role.USER]
        assert len(user_msgs) == 1
        content = user_msgs[0].content or ""
        assert "Step 1: Create logger" in content
        assert "logger exists" in content
        assert "src/logger.py" in content
