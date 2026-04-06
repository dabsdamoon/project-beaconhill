import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from beaconhill.models import Message, Role, ToolCall
from beaconhill.session import Session


class TestResolveSessionPath:
    def _resolve(self, ref, session_dir=None):
        from beaconhill.cli import _resolve_session_path
        return _resolve_session_path(ref, session_dir)

    def test_absolute_path(self, tmp_path):
        session_file = tmp_path / "test.jsonl"
        session_file.write_text("{}")
        result = self._resolve(str(session_file))
        assert result == session_file

    def test_session_id_full(self, tmp_path):
        session = Session(model="test", session_dir=tmp_path)
        session_id = session.meta.session_id
        result = self._resolve(session_id, session_dir=tmp_path)
        assert result == session.path

    def test_session_id_prefix(self, tmp_path):
        session = Session(model="test", session_dir=tmp_path)
        prefix = session.meta.session_id[:8]
        result = self._resolve(prefix, session_dir=tmp_path)
        assert result == session.path

    def test_not_found_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            self._resolve("nonexistent", session_dir=tmp_path)

    def test_ambiguous_exits(self, tmp_path):
        # Create two files with a shared prefix to trigger ambiguous match
        (tmp_path / "shared-aaa.jsonl").write_text("{}")
        (tmp_path / "shared-bbb.jsonl").write_text("{}")
        with pytest.raises(SystemExit):
            self._resolve("shared", session_dir=tmp_path)


class TestReplaySession:
    def test_replay_outputs_messages(self, tmp_path, capsys):
        session = Session(model="test-model", session_dir=tmp_path)
        session.append(Message(role=Role.SYSTEM, content="system prompt"))
        session.append(Message(role=Role.USER, content="hello"))
        session.append(Message(role=Role.ASSISTANT, content="hi there"))

        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.cli import _replay_session
            _replay_session(session.path)

        output = capsys.readouterr().out
        assert "hello" in output
        assert "hi there" in output
        assert "end of session" in output
        # System prompt should not be displayed
        assert "system prompt" not in output

    def test_replay_shows_tool_calls(self, tmp_path, capsys):
        session = Session(model="test", session_dir=tmp_path)
        session.append(Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="bash", arguments={"command": "ls"})],
        ))
        session.append(Message(role=Role.TOOL, content="file1.py\nfile2.py"))
        session.append(Message(role=Role.ASSISTANT, content="Found 2 files."))

        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.cli import _replay_session
            _replay_session(session.path)

        output = capsys.readouterr().out
        assert "bash" in output
        assert "file1.py" in output
        assert "Found 2 files" in output


class TestParseArgs:
    def test_defaults(self):
        with patch("sys.argv", ["beaconhill"]):
            from beaconhill.cli import parse_args
            args = parse_args()
            assert args.model == "gemma4:26b"
            assert args.host == "http://localhost:11434"
            assert args.allow_all is False
            assert args.resume is None
            assert args.replay is None
            assert args.prompt is None

    def test_all_flags(self):
        with patch("sys.argv", [
            "beaconhill",
            "--model", "custom:7b",
            "--host", "http://other:9999",
            "--allow-all",
            "--resume", "abc123",
            "--prompt", "test prompt",
        ]):
            from beaconhill.cli import parse_args
            args = parse_args()
            assert args.model == "custom:7b"
            assert args.host == "http://other:9999"
            assert args.allow_all is True
            assert args.resume == "abc123"
            assert args.prompt == "test prompt"


class TestAgenticLoop:
    def test_text_response_prints_and_saves(self, tmp_path, capsys):
        from beaconhill.cli import _run_agentic_loop
        from beaconhill.tools import create_default_registry

        # Mock client that returns a text response
        mock_client = MagicMock()
        text_msg = Message(role=Role.ASSISTANT, content="the answer")

        def _chunks():
            yield "the answer"

        mock_client.chat_or_stream.return_value = (None, _chunks())
        mock_client.last_prompt_tokens = 100

        session = Session(model="test", session_dir=tmp_path)
        session.append(Message(role=Role.SYSTEM, content="system"))
        session.append(Message(role=Role.USER, content="question"))

        registry = create_default_registry()
        tools = registry.to_ollama()

        with patch("beaconhill.ui._use_color", return_value=False):
            _run_agentic_loop(mock_client, registry, session, tools, allow_all=True)

        output = capsys.readouterr().out
        assert "the answer" in output
        # Session should have the assistant message appended
        assert session.messages[-1].role == Role.ASSISTANT
        assert session.messages[-1].content == "the answer"

    def test_tool_call_then_text(self, tmp_path, capsys):
        from beaconhill.cli import _run_agentic_loop
        from beaconhill.tools import create_default_registry

        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="glob", arguments={"pattern": "*.py"})],
        )

        def _final_chunks():
            yield "found files"

        call_count = [0]

        def chat_or_stream_side_effect(messages, tools=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final_chunks()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = chat_or_stream_side_effect
        mock_client.last_prompt_tokens = 50

        session = Session(model="test", session_dir=tmp_path)
        session.append(Message(role=Role.SYSTEM, content="system"))
        session.append(Message(role=Role.USER, content="find files"))

        registry = create_default_registry()
        tools = registry.to_ollama()

        with patch("beaconhill.ui._use_color", return_value=False):
            _run_agentic_loop(mock_client, registry, session, tools, allow_all=True)

        output = capsys.readouterr().out
        assert "glob" in output
        assert "found files" in output

    def test_denied_tool_sends_denial(self, tmp_path, capsys):
        from beaconhill.cli import _run_agentic_loop
        from beaconhill.tools import Permission, Policy, ToolRegistry, ToolSpec

        # Registry with a DENY policy on EXECUTE
        registry = ToolRegistry(policies={
            Permission.READ: Policy.ALLOW,
            Permission.WRITE: Policy.DENY,
            Permission.EXECUTE: Policy.DENY,
        })
        registry.register(ToolSpec(
            name="bash",
            description="run command",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.EXECUTE,
            fn=lambda args: "should not run",
        ))

        tool_msg = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(name="bash", arguments={"command": "rm -rf /"})],
        )

        def _final():
            yield "ok"

        call_count = [0]

        def side_effect(messages, tools=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return tool_msg, None
            return None, _final()

        mock_client = MagicMock()
        mock_client.chat_or_stream.side_effect = side_effect
        mock_client.last_prompt_tokens = 0

        session = Session(model="test", session_dir=tmp_path)
        session.append(Message(role=Role.SYSTEM, content="sys"))
        session.append(Message(role=Role.USER, content="do bad thing"))

        with patch("beaconhill.ui._use_color", return_value=False):
            _run_agentic_loop(mock_client, registry, session, registry.to_ollama(), allow_all=False)

        # Check that a denial message was sent to the model
        tool_results = [m for m in session.messages if m.role == Role.TOOL]
        assert any("denied" in (m.content or "").lower() for m in tool_results)
