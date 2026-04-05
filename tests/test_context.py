from __future__ import annotations

from beaconhill.context import (
    CHARS_PER_TOKEN,
    DEFAULT_CONTEXT_LIMIT,
    KEEP_RECENT,
    RESPONSE_RESERVE,
    compact_messages,
    estimate_tokens,
    needs_compaction,
)
from beaconhill.models import Message, Role, ToolCall


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens([]) == 0

    def test_text_messages(self):
        msgs = [Message(role=Role.USER, content="hello world")]
        tokens = estimate_tokens(msgs)
        assert tokens == len("hello world") // CHARS_PER_TOKEN

    def test_includes_tool_calls(self):
        tc = ToolCall(name="bash", arguments={"command": "ls -la"})
        msgs = [Message(role=Role.ASSISTANT, tool_calls=[tc])]
        tokens = estimate_tokens(msgs)
        assert tokens > 0

    def test_none_content_handled(self):
        msgs = [Message(role=Role.ASSISTANT, content=None)]
        assert estimate_tokens(msgs) == 0


class TestNeedsCompaction:
    def test_small_context_no_compaction(self):
        msgs = [Message(role=Role.USER, content="short")]
        assert needs_compaction(msgs) is False

    def test_large_context_triggers(self):
        big = "x" * (DEFAULT_CONTEXT_LIMIT * CHARS_PER_TOKEN)
        msgs = [Message(role=Role.USER, content=big)]
        assert needs_compaction(msgs) is True

    def test_custom_limit(self):
        content = "x" * 500
        msgs = [Message(role=Role.USER, content=content)]
        assert needs_compaction(msgs, context_limit=50) is True
        assert needs_compaction(msgs, context_limit=50000) is False


class TestCompactMessages:
    def _make_messages(self, n: int) -> list[Message]:
        msgs = [Message(role=Role.SYSTEM, content="You are a helpful assistant.")]
        for i in range(n):
            msgs.append(Message(role=Role.USER, content=f"question {i}"))
            msgs.append(Message(role=Role.ASSISTANT, content=f"answer {i}"))
        return msgs

    def test_short_conversation_unchanged(self):
        msgs = self._make_messages(2)  # system + 4 messages = 5
        result = compact_messages(msgs, None)
        assert len(result) == len(msgs)

    def test_long_conversation_compacted(self):
        msgs = self._make_messages(20)  # system + 40 = 41 messages
        result = compact_messages(msgs, None)
        # Should be: system + summary + KEEP_RECENT
        assert len(result) == 1 + 1 + KEEP_RECENT
        assert result[0].role == Role.SYSTEM
        assert result[1].role == Role.ASSISTANT
        assert "[Earlier conversation summary]" in result[1].content

    def test_preserves_system_prompt(self):
        msgs = self._make_messages(20)
        result = compact_messages(msgs, None)
        assert result[0].content == "You are a helpful assistant."

    def test_preserves_recent_messages(self):
        msgs = self._make_messages(20)
        result = compact_messages(msgs, None)
        recent = result[2:]  # skip system + summary
        original_recent = msgs[-KEEP_RECENT:]
        for r, o in zip(recent, original_recent):
            assert r.content == o.content

    def test_tool_calls_summarized(self):
        msgs = [
            Message(role=Role.SYSTEM, content="system"),
        ]
        # Add old messages with tool calls
        for _ in range(20):
            tc = ToolCall(name="bash", arguments={"command": "ls"})
            msgs.append(Message(role=Role.ASSISTANT, tool_calls=[tc]))
            msgs.append(Message(role=Role.TOOL, content="file1.py", tool_call_id="bash"))
            msgs.append(Message(role=Role.USER, content="next"))

        result = compact_messages(msgs, None)
        summary = result[1].content
        assert "bash" in summary
