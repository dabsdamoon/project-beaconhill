from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from beaconhill.models import Message

DEFAULT_SESSION_DIR = Path.home() / ".beaconhill" / "sessions"


@dataclass
class SessionMeta:
    session_id: str
    created_at: str
    model: str
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "_meta": True,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "model": self.model,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionMeta:
        return cls(
            session_id=d["session_id"],
            created_at=d["created_at"],
            model=d["model"],
            version=d.get("version", 1),
        )


class Session:
    def __init__(
        self,
        model: str = "gemma4:26b",
        session_dir: Path | None = None,
    ) -> None:
        self.meta = SessionMeta(
            session_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            model=model,
        )
        self.messages: list[Message] = []

        dir_ = session_dir or DEFAULT_SESSION_DIR
        dir_.mkdir(parents=True, exist_ok=True)
        self.path = dir_ / f"{self.meta.session_id}.jsonl"

        self._write_line(self.meta.to_dict())

    def append(self, message: Message) -> None:
        self.messages.append(message)
        self._write_line(message.to_dict())

    def _write_line(self, data: dict[str, Any]) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> Session:
        session = object.__new__(cls)
        session.path = path
        session.messages = []

        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("_meta"):
                    session.meta = SessionMeta.from_dict(data)
                else:
                    session.messages.append(Message.from_dict(data))

        return session

    def to_ollama_messages(self) -> list[dict[str, Any]]:
        return [m.to_ollama() for m in self.messages]
