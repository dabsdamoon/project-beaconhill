from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GLOBAL_CONFIG_PATH = Path.home() / ".beaconhill" / "config.json"
PROJECT_CONFIG_NAME = ".beaconhill/config.json"


@dataclass
class Config:
    model: str = "gemma4:26b"
    host: str = "http://localhost:11434"
    session_dir: str | None = None
    allow_all: bool = False
    context_limit: int = 8192

    @classmethod
    def load(cls, project_dir: Path | None = None) -> Config:
        """Load config with layered precedence: defaults < global < project."""
        config = cls()

        # Global config
        if GLOBAL_CONFIG_PATH.exists():
            config._merge(json.loads(GLOBAL_CONFIG_PATH.read_text()))

        # Project-level config
        if project_dir:
            project_config = project_dir / PROJECT_CONFIG_NAME
            if project_config.exists():
                config._merge(json.loads(project_config.read_text()))

        return config

    def _merge(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def apply_cli_overrides(self, args: Any) -> None:
        """CLI args override config values (only if explicitly set)."""
        if args.model != "gemma4:26b":
            self.model = args.model
        if args.host != "http://localhost:11434":
            self.host = args.host
        if args.session_dir is not None:
            self.session_dir = args.session_dir
        if args.allow_all:
            self.allow_all = True
