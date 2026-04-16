"""Tests for the evaluator: parsing, read-only policy, evidence collection, retry loop."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from beaconhill.evaluator import (
    _parse_evaluation,
    collect_evidence,
    create_evaluator_registry,
    evaluate,
)
from beaconhill.models import Message, Role, ToolCall
from beaconhill.plan import (
    EvaluationResult,
    Plan,
    PlanStep,
    StepEvidence,
    StepStatus,
)
from beaconhill.session import Session
from beaconhill.tools import Permission, Policy, create_default_registry


def _plan(step_ids: list[int]) -> Plan:
    return Plan(
        goal="g",
        steps=[
            PlanStep(id=i, description=f"step {i}", acceptance_criteria=["c"])
            for i in step_ids
        ],
    )


class TestCreateEvaluatorRegistry:
    def test_write_tools_never_registered(self):
        base = create_default_registry()
        readonly = create_evaluator_registry(base)
        names = {s.name for s in readonly.list_specs()}
        assert "write_file" not in names
        assert "edit_file" not in names
        # Unregistered tools are implicitly denied.
        assert readonly.check_permission("write_file") == Policy.DENY
        assert readonly.check_permission("edit_file") == Policy.DENY

    def test_read_and_bash_allowed(self):
        base = create_default_registry()
        readonly = create_evaluator_registry(base)
        assert readonly.check_permission("read_file") == Policy.ALLOW
        assert readonly.check_permission("glob") == Policy.ALLOW
        assert readonly.check_permission("grep") == Policy.ALLOW
        # bash is EXECUTE — allowed so evaluator can run grep/test/pytest.
        assert readonly.check_permission("bash") == Policy.ALLOW

    def test_allow_list_filters_tools(self):
        base = create_default_registry()
        readonly = create_evaluator_registry(base, allowed_names=["read_file", "grep"])
        names = {s.name for s in readonly.list_specs()}
        assert names == {"read_file", "grep"}


class TestParseEvaluation:
    def test_valid_pass(self):
        plan = _plan([1, 2])
        payload = json.dumps(
            {
                "overall_passed": True,
                "verdicts": [
                    {"step_id": 1, "passed": True, "issues": []},
                    {"step_id": 2, "passed": True, "issues": []},
                ],
                "summary": "All good.",
            }
        )
        result = _parse_evaluation(payload, plan, iteration=1)
        assert result is not None
        assert result.overall_passed is True
        assert len(result.verdicts) == 2
        assert result.iteration == 1

    def test_valid_fail_with_issues(self):
        plan = _plan([1])
        payload = json.dumps(
            {
                "overall_passed": False,
                "verdicts": [
                    {"step_id": 1, "passed": False, "issues": ["missing file", "no import"]}
                ],
                "summary": "Step 1 incomplete.",
            }
        )
        result = _parse_evaluation(payload, plan, iteration=0)
        assert result is not None
        assert result.overall_passed is False
        assert result.verdicts[0].issues == ["missing file", "no import"]

    def test_overall_passed_inferred_when_missing(self):
        plan = _plan([1, 2])
        payload = json.dumps(
            {
                "verdicts": [
                    {"step_id": 1, "passed": True},
                    {"step_id": 2, "passed": False, "issues": ["x"]},
                ],
                "summary": "mixed",
            }
        )
        result = _parse_evaluation(payload, plan, iteration=0)
        assert result is not None
        assert result.overall_passed is False

    def test_drops_verdicts_for_unknown_step_ids(self):
        plan = _plan([1])
        payload = json.dumps(
            {
                "overall_passed": True,
                "verdicts": [
                    {"step_id": 1, "passed": True},
                    {"step_id": 99, "passed": True},
                ],
                "summary": "",
            }
        )
        result = _parse_evaluation(payload, plan, iteration=0)
        assert result is not None
        assert [v.step_id for v in result.verdicts] == [1]

    def test_malformed_json(self):
        assert _parse_evaluation("not json", _plan([1]), 0) is None

    def test_missing_verdicts(self):
        plan = _plan([1])
        assert _parse_evaluation('{"overall_passed": true}', plan, 0) is None

    def test_empty_verdicts_rejected(self):
        plan = _plan([1])
        payload = '{"verdicts": [], "summary": "x"}'
        assert _parse_evaluation(payload, plan, 0) is None

    def test_verdict_wrong_types(self):
        plan = _plan([1])
        payload = '{"verdicts": [{"step_id": "1", "passed": true}]}'
        assert _parse_evaluation(payload, plan, 0) is None


class TestEvaluateLoop:
    def _client_seq(self, responses: list[Message]) -> MagicMock:
        client = MagicMock()
        client.chat.side_effect = responses
        return client

    def _capturing_client(self, responses: list[Message]):
        """Client that snapshots the messages list at each chat() call.

        MagicMock retains references to mutable args, so direct inspection of
        call_args_list loses the per-call state.
        """
        snapshots: list[list[Message]] = []
        remaining = list(responses)

        client = MagicMock()

        def _chat(messages, tools=None, on_retry=None):
            snapshots.append(list(messages))
            return remaining.pop(0)

        client.chat.side_effect = _chat
        return client, snapshots

    def test_direct_json_response_parsed(self):
        plan = _plan([1])
        payload = json.dumps(
            {
                "overall_passed": True,
                "verdicts": [{"step_id": 1, "passed": True, "issues": []}],
                "summary": "ok",
            }
        )
        client = self._client_seq(
            [Message(role=Role.ASSISTANT, content=payload)]
        )
        result = evaluate(client, plan, [], create_default_registry())
        assert result.overall_passed is True

    def test_malformed_output_returns_failure(self):
        plan = _plan([1])
        client = self._client_seq(
            [Message(role=Role.ASSISTANT, content="lol no json")]
        )
        result = evaluate(client, plan, [], create_default_registry())
        assert result.overall_passed is False
        assert "could not be parsed" in result.summary

    def test_denies_write_tool_call(self):
        plan = _plan([1])
        payload = json.dumps(
            {
                "overall_passed": False,
                "verdicts": [{"step_id": 1, "passed": False, "issues": ["x"]}],
                "summary": "",
            }
        )
        client, snapshots = self._capturing_client(
            [
                Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            name="write_file",
                            arguments={"file_path": "x.py", "content": "y"},
                        )
                    ],
                ),
                Message(role=Role.ASSISTANT, content=payload),
            ]
        )
        result = evaluate(client, plan, [], create_default_registry())
        assert result.overall_passed is False
        second_call_messages = snapshots[1]
        tool_result_msg = second_call_messages[-1]
        assert tool_result_msg.role == Role.TOOL
        assert "denied" in (tool_result_msg.content or "").lower()

    def test_read_tool_call_executes(self, tmp_path: Path):
        target = tmp_path / "hello.py"
        target.write_text("print('hi')\n")

        plan = _plan([1])
        payload = json.dumps(
            {
                "overall_passed": True,
                "verdicts": [{"step_id": 1, "passed": True, "issues": []}],
                "summary": "ok",
            }
        )
        client, snapshots = self._capturing_client(
            [
                Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            name="read_file", arguments={"file_path": str(target)}
                        )
                    ],
                ),
                Message(role=Role.ASSISTANT, content=payload),
            ]
        )
        result = evaluate(client, plan, [], create_default_registry())
        assert result.overall_passed is True
        second_call_messages = snapshots[1]
        tool_result_msg = second_call_messages[-1]
        assert "print('hi')" in (tool_result_msg.content or "")

    def test_exceeds_max_iterations(self):
        plan = _plan([1])

        def always_tool_call(*args, **kwargs):
            return Message(
                role=Role.ASSISTANT,
                tool_calls=[ToolCall(name="glob", arguments={"pattern": "*"})],
            )

        client = MagicMock()
        client.chat.side_effect = always_tool_call
        result = evaluate(
            client, plan, [], create_default_registry(), max_iterations=3
        )
        assert result.overall_passed is False
        assert "exceeded" in result.summary.lower()


class TestCollectEvidence:
    def test_groups_by_step_boundary(self):
        plan = _plan([1, 2])
        messages = [
            Message(role=Role.USER, content="You are executing step 1 of the plan: x"),
            Message(
                role=Role.ASSISTANT,
                content="done",
                tool_calls=[
                    ToolCall(name="write_file", arguments={"file_path": "a.py", "content": "x"})
                ],
            ),
            Message(role=Role.TOOL, content="wrote", tool_call_id="write_file"),
            Message(role=Role.USER, content="You are executing step 2 of the plan: y"),
            Message(
                role=Role.ASSISTANT,
                content="also done",
                tool_calls=[
                    ToolCall(name="read_file", arguments={"file_path": "b.py"})
                ],
            ),
        ]
        evidence = collect_evidence(messages, plan)
        assert len(evidence) == 2
        assert evidence[0].step_id == 1
        assert "write_file(a.py)" in evidence[0].tool_calls
        assert evidence[0].files_touched == ["a.py"]
        assert evidence[0].assistant_text == "done"
        assert evidence[1].step_id == 2
        assert "read_file(b.py)" in evidence[1].tool_calls

    def test_keeps_most_recent_attempt(self):
        plan = _plan([1])
        messages = [
            Message(role=Role.USER, content="You are executing step 1 of the plan: x"),
            Message(
                role=Role.ASSISTANT,
                tool_calls=[ToolCall(name="write_file", arguments={"file_path": "old.py"})],
                content="first",
            ),
            Message(role=Role.USER, content="You are executing step 1 of the plan: retry"),
            Message(
                role=Role.ASSISTANT,
                tool_calls=[ToolCall(name="write_file", arguments={"file_path": "new.py"})],
                content="second",
            ),
        ]
        evidence = collect_evidence(messages, plan)
        assert len(evidence) == 1
        assert evidence[0].files_touched == ["new.py"]
        assert evidence[0].assistant_text == "second"

    def test_ignores_step_ids_not_in_plan(self):
        plan = _plan([1])
        messages = [
            Message(role=Role.USER, content="You are executing step 99 of the plan: bogus"),
            Message(role=Role.ASSISTANT, content="stray"),
        ]
        evidence = collect_evidence(messages, plan)
        assert evidence == []

    def test_empty_messages(self):
        plan = _plan([1])
        assert collect_evidence([], plan) == []


class TestStepEvidencePrompt:
    def test_renders_compact_summary(self):
        ev = StepEvidence(
            step_id=1,
            tool_calls=["write_file(a.py)", "read_file(b.py)"],
            files_touched=["a.py", "b.py"],
            assistant_text="Wrote both files.",
        )
        text = ev.to_prompt()
        assert "Step 1 evidence" in text
        assert "write_file(a.py)" in text
        assert "a.py, b.py" in text
        assert "Wrote both files" in text

    def test_handles_empty_tool_calls(self):
        ev = StepEvidence(step_id=1)
        assert "(none)" in ev.to_prompt()


class TestOrchestratorRetryLoop:
    """End-to-end: evaluator fails, orchestrator retries failed step, eventually passes."""

    def _make_plan_payload(self) -> str:
        return json.dumps(
            {
                "goal": "two steps",
                "steps": [
                    {"id": 1, "description": "a", "acceptance_criteria": ["c"]},
                    {"id": 2, "description": "b", "acceptance_criteria": ["c"]},
                ],
            }
        )

    def test_fail_then_pass_converges(self, tmp_path: Path):
        from beaconhill.orchestrator import OrchestratorPhase, run_orchestrated

        plan_payload = self._make_plan_payload()
        fail_eval = json.dumps(
            {
                "overall_passed": False,
                "verdicts": [
                    {"step_id": 1, "passed": True, "issues": []},
                    {"step_id": 2, "passed": False, "issues": ["missing import"]},
                ],
                "summary": "step 2 incomplete",
            }
        )
        pass_eval = json.dumps(
            {
                "overall_passed": True,
                "verdicts": [
                    {"step_id": 1, "passed": True, "issues": []},
                    {"step_id": 2, "passed": True, "issues": []},
                ],
                "summary": "all good",
            }
        )
        client = MagicMock()
        client.chat.side_effect = [
            Message(role=Role.ASSISTANT, content=plan_payload),
            Message(role=Role.ASSISTANT, content=fail_eval),
            Message(role=Role.ASSISTANT, content=pass_eval),
        ]
        registry = create_default_registry()
        session = Session(model="test", session_dir=tmp_path)

        with patch("beaconhill.orchestrator.run_agentic_loop") as mock_loop:
            state = run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do two things",
                interactive=False,
                max_eval_iterations=3,
            )

        assert state.phase == OrchestratorPhase.COMPLETE
        assert len(state.evaluation_results) == 2
        assert state.evaluation_results[0].overall_passed is False
        assert state.evaluation_results[1].overall_passed is True
        # First pass: 2 steps. Retry: only step 2. Total = 3.
        assert mock_loop.call_count == 3

    def test_max_iterations_then_fail(self, tmp_path: Path):
        from beaconhill.orchestrator import OrchestratorPhase, run_orchestrated

        plan_payload = self._make_plan_payload()
        fail_eval = json.dumps(
            {
                "overall_passed": False,
                "verdicts": [
                    {"step_id": 1, "passed": False, "issues": ["x"]},
                    {"step_id": 2, "passed": False, "issues": ["y"]},
                ],
                "summary": "no good",
            }
        )
        # Plan call + N failing eval calls
        client = MagicMock()
        client.chat.side_effect = [
            Message(role=Role.ASSISTANT, content=plan_payload),
            *[Message(role=Role.ASSISTANT, content=fail_eval) for _ in range(5)],
        ]
        registry = create_default_registry()
        session = Session(model="test", session_dir=tmp_path)

        with patch("beaconhill.orchestrator.run_agentic_loop"):
            state = run_orchestrated(
                client=client,
                registry=registry,
                session=session,
                tools=[],
                allow_all=True,
                context_limit=4096,
                user_input="do two things",
                interactive=False,
                max_eval_iterations=2,
            )

        assert state.phase == OrchestratorPhase.FAILED
        assert len(state.evaluation_results) == 2

    def test_feedback_included_in_retry_prompt(self, tmp_path: Path):
        from beaconhill.orchestrator import run_orchestrated

        plan_payload = json.dumps(
            {
                "goal": "g",
                "steps": [{"id": 1, "description": "a", "acceptance_criteria": ["c"]}],
            }
        )
        fail_eval = json.dumps(
            {
                "overall_passed": False,
                "verdicts": [
                    {"step_id": 1, "passed": False, "issues": ["specific problem"]}
                ],
                "summary": "try again",
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
            Message(role=Role.ASSISTANT, content=pass_eval),
        ]
        registry = create_default_registry()
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
                max_eval_iterations=2,
            )

        user_msgs = [m.content for m in session.messages if m.role == Role.USER]
        # 2 step prompts: first without feedback, second with evaluator feedback
        assert len(user_msgs) == 2
        assert "Evaluator feedback" not in user_msgs[0]
        assert "specific problem" in user_msgs[1]
