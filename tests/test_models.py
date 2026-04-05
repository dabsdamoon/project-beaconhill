from beaconhill.models import Message, Role, ToolCall


class TestRole:
    def test_str_values(self):
        assert str(Role.USER) == "user"
        assert str(Role.ASSISTANT) == "assistant"
        assert str(Role.SYSTEM) == "system"
        assert str(Role.TOOL) == "tool"

    def test_from_string(self):
        assert Role("user") is Role.USER


class TestToolCall:
    def test_round_trip(self):
        tc = ToolCall(name="read_file", arguments={"path": "/tmp/test.py"})
        d = tc.to_dict()
        assert d == {"name": "read_file", "arguments": {"path": "/tmp/test.py"}}
        assert ToolCall.from_dict(d) == tc


class TestMessage:
    def test_user_message_round_trip(self):
        msg = Message(role=Role.USER, content="hello", timestamp="2026-01-01T00:00:00Z")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "hello", "timestamp": "2026-01-01T00:00:00Z"}
        assert Message.from_dict(d) == msg

    def test_assistant_message_with_tool_calls(self):
        tc = ToolCall(name="bash", arguments={"command": "ls"})
        msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[tc],
            timestamp="2026-01-01T00:00:00Z",
        )
        d = msg.to_dict()
        assert "tool_calls" in d
        assert d["tool_calls"][0]["name"] == "bash"
        restored = Message.from_dict(d)
        assert restored.tool_calls is not None
        assert restored.tool_calls[0].name == "bash"

    def test_content_none_excluded_from_dict(self):
        msg = Message(role=Role.ASSISTANT, timestamp="2026-01-01T00:00:00Z")
        d = msg.to_dict()
        assert "content" not in d

    def test_to_ollama_format(self):
        msg = Message(role=Role.USER, content="hi")
        d = msg.to_ollama()
        assert d == {"role": "user", "content": "hi"}
        assert "timestamp" not in d

    def test_to_ollama_with_tool_calls(self):
        tc = ToolCall(name="bash", arguments={"command": "ls"})
        msg = Message(role=Role.ASSISTANT, tool_calls=[tc])
        d = msg.to_ollama()
        assert d["tool_calls"][0]["function"]["name"] == "bash"
