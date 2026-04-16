"""Tests for the planner: create_plan and JSON extraction."""
import json
from unittest.mock import MagicMock

from beaconhill.models import Message, Role
from beaconhill.plan import Plan
from beaconhill.planner import _extract_json_object, _parse_plan, create_plan


def _mock_client(content: str) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = Message(role=Role.ASSISTANT, content=content)
    return client


class TestExtractJsonObject:
    def test_bare_object(self):
        assert _extract_json_object('{"a": 1}') == '{"a": 1}'

    def test_with_surrounding_text(self):
        text = 'Here is the plan:\n{"goal": "x"}\nDone.'
        assert _extract_json_object(text) == '{"goal": "x"}'

    def test_fenced_json_block(self):
        text = 'Output:\n```json\n{"goal": "x"}\n```'
        assert _extract_json_object(text) == '{"goal": "x"}'

    def test_fenced_without_language(self):
        text = '```\n{"goal": "x"}\n```'
        assert _extract_json_object(text) == '{"goal": "x"}'

    def test_no_object(self):
        assert _extract_json_object("no json here") is None

    def test_empty(self):
        assert _extract_json_object("") is None


class TestParsePlan:
    def test_valid_plan(self):
        payload = json.dumps(
            {
                "goal": "Add logging",
                "steps": [
                    {
                        "id": 1,
                        "description": "Create logger module",
                        "acceptance_criteria": ["logger.py exists"],
                        "files": ["src/logger.py"],
                    },
                    {
                        "id": 2,
                        "description": "Wire it up",
                        "acceptance_criteria": ["main imports logger"],
                        "files": [],
                    },
                ],
            }
        )
        plan = _parse_plan(payload)
        assert plan is not None
        assert plan.goal == "Add logging"
        assert len(plan.steps) == 2
        assert plan.steps[0].files == ["src/logger.py"]
        assert plan.steps[1].files == []

    def test_missing_files_defaults_to_empty(self):
        payload = json.dumps(
            {
                "goal": "x",
                "steps": [
                    {
                        "id": 1,
                        "description": "d",
                        "acceptance_criteria": ["c"],
                    }
                ],
            }
        )
        plan = _parse_plan(payload)
        assert plan is not None
        assert plan.steps[0].files == []

    def test_malformed_json(self):
        assert _parse_plan("{not json") is None

    def test_not_a_dict(self):
        assert _parse_plan("[1, 2, 3]") is None

    def test_empty_steps_rejected(self):
        assert _parse_plan('{"goal": "x", "steps": []}') is None

    def test_step_missing_description(self):
        payload = json.dumps(
            {
                "goal": "x",
                "steps": [{"id": 1, "acceptance_criteria": ["c"]}],
            }
        )
        assert _parse_plan(payload) is None

    def test_step_criteria_not_a_list(self):
        payload = json.dumps(
            {
                "goal": "x",
                "steps": [
                    {"id": 1, "description": "d", "acceptance_criteria": "c"}
                ],
            }
        )
        assert _parse_plan(payload) is None

    def test_id_defaults_when_missing(self):
        payload = json.dumps(
            {
                "goal": "x",
                "steps": [
                    {"description": "a", "acceptance_criteria": ["c"]},
                    {"description": "b", "acceptance_criteria": ["c"]},
                ],
            }
        )
        plan = _parse_plan(payload)
        assert plan is not None
        assert [s.id for s in plan.steps] == [1, 2]


class TestCreatePlan:
    def test_valid_response(self):
        payload = json.dumps(
            {
                "goal": "Refactor auth",
                "steps": [
                    {
                        "id": 1,
                        "description": "Extract token logic",
                        "acceptance_criteria": ["token.py exists"],
                        "files": ["src/token.py"],
                    }
                ],
            }
        )
        client = _mock_client(payload)
        plan = create_plan(client, "Refactor the auth module")
        assert isinstance(plan, Plan)
        assert plan.goal == "Refactor auth"
        assert len(plan.steps) == 1

    def test_fenced_response(self):
        payload = (
            "Sure, here's the plan:\n```json\n"
            + json.dumps(
                {
                    "goal": "g",
                    "steps": [
                        {
                            "id": 1,
                            "description": "d",
                            "acceptance_criteria": ["c"],
                            "files": [],
                        }
                    ],
                }
            )
            + "\n```"
        )
        client = _mock_client(payload)
        plan = create_plan(client, "do thing")
        assert plan.goal == "g"

    def test_fallback_on_malformed(self):
        client = _mock_client("i cannot make a plan sorry")
        plan = create_plan(client, "Do the thing")
        assert plan.goal == "Do the thing"
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "Do the thing"

    def test_fallback_on_empty_response(self):
        client = _mock_client("")
        plan = create_plan(client, "Do the thing")
        assert len(plan.steps) == 1

    def test_planner_receives_system_and_user_messages(self):
        client = _mock_client('{"goal": "g", "steps": [{"id":1,"description":"d","acceptance_criteria":["c"]}]}')
        create_plan(client, "user ask", project_context="cwd: /tmp")
        args, _ = client.chat.call_args
        messages = args[0]
        assert len(messages) == 2
        assert messages[0].role == Role.SYSTEM
        assert "Planner" in (messages[0].content or "")
        assert messages[1].role == Role.USER
        assert "user ask" in (messages[1].content or "")
        assert "cwd: /tmp" in (messages[1].content or "")


class TestPlanApprovalPrompt:
    def test_approve_on_y(self, monkeypatch):
        from beaconhill import ui

        monkeypatch.setattr("builtins.input", lambda _: "y")
        assert ui.plan_approval_prompt() == "approve"

    def test_approve_on_empty(self, monkeypatch):
        from beaconhill import ui

        monkeypatch.setattr("builtins.input", lambda _: "")
        assert ui.plan_approval_prompt() == "approve"

    def test_edit_on_e(self, monkeypatch):
        from beaconhill import ui

        monkeypatch.setattr("builtins.input", lambda _: "e")
        assert ui.plan_approval_prompt() == "edit"

    def test_reject_on_n(self, monkeypatch):
        from beaconhill import ui

        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert ui.plan_approval_prompt() == "reject"

    def test_reject_on_eof(self, monkeypatch):
        from beaconhill import ui

        def _raise(_):
            raise EOFError

        monkeypatch.setattr("builtins.input", _raise)
        assert ui.plan_approval_prompt() == "reject"


class TestDisplayPlan:
    def test_prints_goal_and_steps(self, capsys):
        from beaconhill import ui
        from beaconhill.plan import PlanStep

        plan = Plan(
            goal="Ship the feature",
            steps=[
                PlanStep(
                    id=1,
                    description="Write code",
                    acceptance_criteria=["compiles"],
                    files=["src/main.py"],
                )
            ],
        )
        ui.display_plan(plan)
        out = capsys.readouterr().out
        assert "Ship the feature" in out
        assert "Step 1:" in out
        assert "Write code" in out
        assert "src/main.py" in out
        assert "compiles" in out
