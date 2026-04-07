from unittest.mock import MagicMock, patch

from beaconhill.agent import MAX_ITERATIONS, build_system_prompt, run_agent_turn
from beaconhill.models import Message, Role, ToolCall
from beaconhill.tools import ToolRegistry, ToolResult, create_default_registry


class TestBuildSystemPrompt:
    def test_contains_working_directory(self, tmp_path):
        prompt = build_system_prompt(working_dir=str(tmp_path))
        assert str(tmp_path) in prompt

    def test_contains_beaconhill_identity(self):
        prompt = build_system_prompt(working_dir="/tmp")
        assert "Beaconhill" in prompt

    def test_lists_files(self, tmp_path):
        (tmp_path / "foo.py").write_text("pass")
        (tmp_path / "bar.txt").write_text("hello")
        prompt = build_system_prompt(working_dir=str(tmp_path))
        assert "foo.py" in prompt
        assert "bar.txt" in prompt

    def test_lists_directories(self, tmp_path):
        (tmp_path / "src").mkdir()
        prompt = build_system_prompt(working_dir=str(tmp_path))
        assert "[dir]" in prompt
        assert "src" in prompt

    def test_handles_empty_directory(self, tmp_path):
        prompt = build_system_prompt(working_dir=str(tmp_path))
        assert "Working Directory" in prompt

    def test_uses_cwd_when_none(self):
        import os
        prompt = build_system_prompt(working_dir=None)
        assert os.getcwd() in prompt


class TestRunAgentTurn:
    def _make_mock_client(self, responses: list[Message]):
        client = MagicMock()
        client.chat.side_effect = responses
        return client

    def test_simple_text_response(self):
        response = Message(role=Role.ASSISTANT, content="Hello!")
        client = self._make_mock_client([response])
        registry = ToolRegistry()

        messages, text = run_agent_turn("Hi", client, registry)

        assert text == "Hello!"
        assert len(messages) == 3  # system + user + assistant
        assert messages[0].role == Role.SYSTEM
        assert messages[1].role == Role.USER
        assert messages[1].content == "Hi"
        assert messages[2].role == Role.ASSISTANT

    def test_tool_call_then_text(self):
        tool_response = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="test_tool", arguments={"arg": "val"})],
        )
        final_response = Message(role=Role.ASSISTANT, content="Done!")
        client = self._make_mock_client([tool_response, final_response])

        registry = ToolRegistry()
        registry.register(MagicMock(
            name="test_tool",
            fn=lambda args: "tool output",
            required_permission=MagicMock(),
        ))
        # Mock execute to return a result
        registry.execute = MagicMock(return_value=ToolResult(output="tool output"))

        messages, text = run_agent_turn("Do something", client, registry)

        assert text == "Done!"
        # system + user + assistant(tool_call) + tool_result + assistant(final)
        assert len(messages) == 5
        assert messages[2].tool_calls is not None
        assert messages[3].role == Role.TOOL
        assert messages[3].content == "tool output"

    def test_uses_existing_messages(self):
        existing = [
            Message(role=Role.SYSTEM, content="system"),
            Message(role=Role.USER, content="prev"),
            Message(role=Role.ASSISTANT, content="prev response"),
        ]
        response = Message(role=Role.ASSISTANT, content="new response")
        client = self._make_mock_client([response])
        registry = ToolRegistry()

        messages, text = run_agent_turn("new question", client, registry, messages=existing)

        assert text == "new response"
        assert len(messages) == 5  # 3 existing + user + assistant
        assert messages[3].content == "new question"

    def test_max_iterations_safety(self):
        # Every response has a tool call, so loop never naturally ends
        tool_response = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="loop_tool", arguments={})],
        )
        client = MagicMock()
        client.chat.return_value = tool_response

        registry = ToolRegistry()
        registry.execute = MagicMock(return_value=ToolResult(output="ok"))

        messages, text = run_agent_turn("infinite", client, registry)

        assert client.chat.call_count == MAX_ITERATIONS
        assert text == ""  # no final text since model never stopped

    def test_tool_error_sent_back(self):
        tool_response = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="bad_tool", arguments={})],
        )
        final = Message(role=Role.ASSISTANT, content="handled error")
        client = self._make_mock_client([tool_response, final])

        registry = ToolRegistry()
        registry.execute = MagicMock(
            return_value=ToolResult(output="Error: something broke", is_error=True)
        )

        messages, text = run_agent_turn("try bad tool", client, registry)

        assert text == "handled error"
        tool_msg = messages[3]
        assert tool_msg.role == Role.TOOL
        assert "Error" in tool_msg.content
