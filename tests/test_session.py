import json
from pathlib import Path

from beaconhill.models import Message, Role
from beaconhill.session import Session


class TestSession:
    def test_create_writes_metadata(self, tmp_path: Path):
        session = Session(model="test-model", session_dir=tmp_path)
        assert session.path.exists()

        with open(session.path) as f:
            first_line = json.loads(f.readline())
        assert first_line["_meta"] is True
        assert first_line["model"] == "test-model"
        assert "session_id" in first_line

    def test_append_persists(self, tmp_path: Path):
        session = Session(session_dir=tmp_path)
        msg = Message(role=Role.USER, content="hello")
        session.append(msg)

        assert len(session.messages) == 1

        with open(session.path) as f:
            lines = f.readlines()
        assert len(lines) == 2  # meta + 1 message
        data = json.loads(lines[1])
        assert data["role"] == "user"
        assert data["content"] == "hello"

    def test_load_round_trip(self, tmp_path: Path):
        session = Session(model="gemma4:26b", session_dir=tmp_path)
        session.append(Message(role=Role.USER, content="hello"))
        session.append(Message(role=Role.ASSISTANT, content="hi there"))

        loaded = Session.load(session.path)
        assert loaded.meta.session_id == session.meta.session_id
        assert loaded.meta.model == "gemma4:26b"
        assert len(loaded.messages) == 2
        assert loaded.messages[0].content == "hello"
        assert loaded.messages[1].content == "hi there"

    def test_to_ollama_messages(self, tmp_path: Path):
        session = Session(session_dir=tmp_path)
        session.append(Message(role=Role.USER, content="hello"))
        session.append(Message(role=Role.ASSISTANT, content="hi"))

        ollama_msgs = session.to_ollama_messages()
        assert len(ollama_msgs) == 2
        assert ollama_msgs[0] == {"role": "user", "content": "hello"}
        assert ollama_msgs[1] == {"role": "assistant", "content": "hi"}
