from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Literal
from rich.console import Console
from rich.markdown import Markdown

from beaconhill.plan import Plan

PlanApproval = Literal["approve", "reject", "edit"]

_console = Console()

# --- ANSI color codes ---
...
# --- ANSI color codes ---

_AMBER = "\033[33m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_GREY = "\033[90m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def amber(text: str) -> str:
    return f"{_AMBER}{text}{_RESET}" if _use_color() else text


def green(text: str) -> str:
    return f"{_GREEN}{text}{_RESET}" if _use_color() else text


def red(text: str) -> str:
    return f"{_RED}{text}{_RESET}" if _use_color() else text


def grey(text: str) -> str:
    return f"{_GREY}{text}{_RESET}" if _use_color() else text


def bold(text: str) -> str:
    return f"{_BOLD}{text}{_RESET}" if _use_color() else text


def bold_amber(text: str) -> str:
    return f"{_BOLD}{_AMBER}{text}{_RESET}" if _use_color() else text


# --- Branded output functions ---

TRAY_WIDTH = 50


def banner(model: str, session_id: str, resumed: bool = False, msg_count: int = 0) -> None:
    print()
    print(f"  {bold_amber('Beaconhill')} {grey('v0.1.0')}")
    print(f"  {green('[*]')} Beacon lit. Model loaded.")
    print(f"  {grey(f'model: {model} | session: {session_id[:8]}')}")
    if resumed:
        print(f"  {grey(f'{msg_count} messages resumed')}")
    print(f"  {grey('Type /quit to extinguish the beacon.')}")
    print()


def banner_oneshot(model: str) -> None:
    print(f"  {bold_amber('Beaconhill')} {grey('v0.1.0')} {grey(f'| {model}')}")


def goodbye() -> None:
    print(f"\n  {grey('Beacon extinguished. Session saved.')}")


def tool_start(name: str, summary: str) -> None:
    header = f"--- {name}: {summary} "
    header = header.ljust(TRAY_WIDTH, "-")
    print(grey(header))


def tool_end() -> None:
    print(grey("-" * TRAY_WIDTH))


def tool_error(text: str) -> None:
    print(red(f"  {text}"))


def tool_denied(name: str, by_user: bool = False) -> None:
    who = " by user" if by_user else ""
    header = f"--- {name} (denied{who}) "
    header = header.ljust(TRAY_WIDTH, "-")
    print(amber(header))


def permission_prompt(name: str, arguments: dict[str, Any]) -> bool:
    header = f"--- {name} (requires approval) "
    header = header.ljust(TRAY_WIDTH, "-")
    print(amber(header))
    for key, value in arguments.items():
        val_str = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        print(f"  {grey(key + ':')} {val_str}")
    print(grey("--"))
    try:
        answer = input(f"  Allow? {grey('[y/N]')} ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        print(grey("-" * TRAY_WIDTH))
        return False
    print(grey("-" * TRAY_WIDTH))
    return answer in ("y", "yes")


def info(text: str) -> None:
    print(grey(f"  {text}"))


def error(text: str) -> None:
    print(red(f"  {text}"))


def warning(text: str) -> None:
    print(amber(f"  {text}"))


def token_count(prompt_tokens: int, limit: int) -> None:
    print(grey(f"  [tokens: {prompt_tokens}/{limit}]"))


def replay_header(session_id: str, created: str, model: str) -> None:
    print(f"\n  {bold_amber('Replaying session')} {grey(session_id[:8])}")
    print(f"  {grey(f'Created: {created} | Model: {model}')}")
    print(grey("-" * TRAY_WIDTH))


def replay_footer() -> None:
    print(f"\n{grey('─' * TRAY_WIDTH)}")
    print(grey("  (end of session)"))


def replay_user(text: str) -> None:
    print(f"\n  {amber('>>>')} {text}")


def replay_tool(name: str, summary: str) -> None:
    print(f"  {grey(f'[tool] {name}: {summary}')}")


def replay_tool_output(text: str) -> None:
    if len(text) > 200:
        text = text[:200] + "..."
    print(f"  {grey(f'-> {text}')}")


def replay_assistant(text: str) -> None:
    _console.print(f"  ", end="")
    _console.print(Markdown(text))


# --- Thinking Pulse ---

class ThinkingPulse:
    def __init__(self, label: str = "thinking") -> None:
        self._label = label
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not sys.stdout.isatty():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        # Clear the pulse line
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _run(self) -> None:
        frames = ["*  ", " * ", "  *", " * "]
        idx = 0
        while not self._stop_event.is_set():
            if _use_color():
                text = f"\r  {_AMBER}{frames[idx]}{_RESET} {_GREY}{self._label}...{_RESET}"
            else:
                text = f"\r  {frames[idx]} {self._label}..."
            sys.stdout.write(text)
            sys.stdout.flush()
            idx = (idx + 1) % len(frames)
            self._stop_event.wait(0.3)


def display_plan(plan: Plan) -> None:
    header = f"--- plan: {plan.goal} "
    header = header.ljust(TRAY_WIDTH, "-")
    print()
    print(amber(header))
    for step in plan.steps:
        print(f"  {bold(f'Step {step.id}:')} {step.description}")
        if step.files:
            print(f"    {grey('files:')} {', '.join(step.files)}")
        for criterion in step.acceptance_criteria:
            print(f"    {grey('-')} {criterion}")
    print(grey("-" * TRAY_WIDTH))


def plan_approval_prompt() -> PlanApproval:
    try:
        answer = input(
            f"  Approve plan? {grey('[y=approve / n=reject / e=edit]')} "
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return "reject"
    if answer in ("y", "yes", ""):
        return "approve"
    if answer in ("e", "edit"):
        return "edit"
    return "reject"


def summarize_args(arguments: dict[str, Any]) -> str:
    if "command" in arguments:
        return arguments["command"]
    if "file_path" in arguments:
        return arguments["file_path"]
    if "pattern" in arguments:
        return arguments["pattern"]
    return json.dumps(arguments, ensure_ascii=False)
