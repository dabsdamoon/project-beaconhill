"""Integration tests for run_orchestrated: plan -> approval -> per-step generate."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from beaconhill.models import Message, Role
from beaconhill.orchestrator import OrchestratorPhase, run_orchestrated
from beaconhill.plan import StepStatus
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
