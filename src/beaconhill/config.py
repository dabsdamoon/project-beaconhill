from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GLOBAL_CONFIG_PATH = Path.home() / ".beaconhill" / "config.json"
PROJECT_CONFIG_NAME = ".beaconhill/config.json"


PLAN_MODE_AUTO = "auto"
PLAN_MODE_ALWAYS = "always"
PLAN_MODE_NEVER = "never"
VALID_PLAN_MODES = (PLAN_MODE_AUTO, PLAN_MODE_ALWAYS, PLAN_MODE_NEVER)


_MULTI_STEP_KEYWORDS = re.compile(
    r"\b(and then|and also|then |after that|first,|multiple|refactor|implement|add .+? and|"
    r"across|throughout|rename .+? and|migrate|restructure)\b",
    re.IGNORECASE,
)


def should_plan(user_input: str, plan_mode: str) -> bool:
    """Decide whether a user input warrants orchestrated plan-generate mode.

    - `always` / `never` are absolute.
    - `auto` heuristic: long input OR contains explicit multi-step phrasing.
    """
    if plan_mode == PLAN_MODE_ALWAYS:
        return True
    if plan_mode == PLAN_MODE_NEVER:
        return False
    if len(user_input) > 200:
        return True
    if _MULTI_STEP_KEYWORDS.search(user_input):
        return True
    return False


@dataclass
class Config:
    model: str = "gemma4:26b"
    host: str = "http://localhost:11434"
    session_dir: str | None = None
    allow_all: bool = False
    context_limit: int = 32768
    plan_mode: str = PLAN_MODE_AUTO
    max_eval_iterations: int = 3
    plan_approval: bool = True
    evaluator_tools: list[str] = field(
        default_factory=lambda: ["read_file", "glob", "grep", "bash"]
    )

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
        plan_mode = getattr(args, "plan_mode", None)
        if plan_mode is not None:
            if plan_mode not in VALID_PLAN_MODES:
                raise ValueError(
                    f"plan_mode must be one of {VALID_PLAN_MODES}, got {plan_mode!r}"
                )
            self.plan_mode = plan_mode
        # Legacy --plan switch: force "always"
        if getattr(args, "plan", False):
            self.plan_mode = PLAN_MODE_ALWAYS
