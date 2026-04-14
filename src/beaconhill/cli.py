from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from beaconhill.agent import MAX_ITERATIONS, build_system_prompt
from beaconhill.client import OllamaClient
from beaconhill.config import Config
from beaconhill.models import Message, Role
from beaconhill.orchestrator import run_orchestrated
from beaconhill.runtime import run_agentic_loop
from beaconhill.session import DEFAULT_SESSION_DIR, Session
from beaconhill.tools import create_default_registry
from beaconhill import ui


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="beaconhill",
        description="Local-first coding agent harness",
    )
    parser.add_argument("--model", default="gemma4:26b", help="Ollama model name")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama API host")
    parser.add_argument("--session-dir", default=None, help="Directory for session JSONL files")
    parser.add_argument("--allow-all", action="store_true", help="Skip permission prompts")
    parser.add_argument("--resume", default=None, help="Session ID or path to resume")
    parser.add_argument("--replay", default=None, help="Session ID or path to replay (read-only)")
    parser.add_argument("--prompt", default=None, help="One-shot mode: run a single prompt and exit")
    parser.add_argument(
        "--image",
        action="append",
        default=None,
        help="Attach an image file to the prompt (repeatable). Requires a vision-capable model.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Run in orchestrated plan-generate mode: produce a plan before executing.",
    )
    return parser.parse_args()


def _validate_image_paths(paths: list[str]) -> list[str]:
    resolved: list[str] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.exists() or not p.is_file():
            ui.error(f"Image not found: {raw}")
            sys.exit(1)
        resolved.append(str(p))
    return resolved


def _resolve_session_path(ref: str, session_dir: Path | None = None) -> Path:
    p = Path(ref)
    if p.exists():
        return p
    dir_ = session_dir or DEFAULT_SESSION_DIR
    candidate = dir_ / f"{ref}.jsonl"
    if candidate.exists():
        return candidate
    if dir_.exists():
        matches = sorted(dir_.glob(f"{ref}*.jsonl"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            ui.error(f"Ambiguous session ID, matches: {[m.stem for m in matches]}")
            sys.exit(1)
    ui.error(f"Session not found: {ref}")
    sys.exit(1)


def _replay_session(path: Path) -> None:
    session = Session.load(path)
    ui.replay_header(session.meta.session_id, session.meta.created_at, session.meta.model)
    for msg in session.messages:
        if msg.role == Role.SYSTEM:
            continue
        if msg.role == Role.USER:
            ui.replay_user(msg.content or "")
        elif msg.role == Role.ASSISTANT:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    ui.replay_tool(tc.name, ui.summarize_args(tc.arguments))
            if msg.content:
                ui.replay_assistant(msg.content)
        elif msg.role == Role.TOOL:
            ui.replay_tool_output(msg.content or "")
    ui.replay_footer()


def main() -> None:
    args = parse_args()

    config = Config.load(project_dir=Path.cwd())
    config.apply_cli_overrides(args)

    session_dir = Path(config.session_dir) if config.session_dir else None

    # Replay mode (read-only, no Ollama needed)
    if args.replay:
        path = _resolve_session_path(args.replay, session_dir)
        _replay_session(path)
        return

    client = OllamaClient(model=config.model, host=config.host)
    registry = create_default_registry()

    # Resume or new session
    if args.resume:
        path = _resolve_session_path(args.resume, session_dir)
        session = Session.load(path)
        ui.banner(config.model, session.meta.session_id, resumed=True, msg_count=len(session.messages))
    else:
        session = Session(model=config.model, session_dir=session_dir)
        if args.prompt:
            ui.banner_oneshot(config.model)
        else:
            ui.banner(config.model, session.meta.session_id)
        system_msg = Message(role=Role.SYSTEM, content=build_system_prompt())
        session.append(system_msg)

    tools = registry.to_ollama()

    # One-shot mode
    if args.prompt:
        images = _validate_image_paths(args.image) if args.image else None
        if args.plan:
            try:
                run_orchestrated(
                    client=client,
                    registry=registry,
                    session=session,
                    tools=tools,
                    allow_all=config.allow_all,
                    context_limit=config.context_limit,
                    user_input=args.prompt,
                    interactive=False,
                )
            except ConnectionError as e:
                ui.error(f"Beacon flickering. {e}")
                sys.exit(1)
            return

        user_msg = Message(role=Role.USER, content=args.prompt, images=images)
        session.append(user_msg)
        try:
            _run_agentic_loop(client, registry, session, tools, config.allow_all, config.context_limit)
        except ConnectionError as e:
            ui.error(f"Beacon flickering. {e}")
            sys.exit(1)
        return

    # Interactive REPL
    pending_images: list[str] = []
    plan_next_turn = False
    while True:
        try:
            prompt_str = ui.amber(">>> ") if ui._use_color() else ">>> "
            user_input = input(prompt_str)
        except (KeyboardInterrupt, EOFError):
            ui.goodbye()
            break

        stripped = user_input.strip()
        if not stripped:
            continue
        if stripped in ("/quit", "/exit"):
            ui.goodbye()
            break
        if stripped == "/session":
            ui.info(f"Session: {session.path}")
            continue
        if stripped.startswith("/img"):
            parts = stripped.split(maxsplit=1)
            if len(parts) == 1:
                if pending_images:
                    ui.info(f"Pending images: {pending_images}")
                else:
                    ui.info("Usage: /img <path>  (attaches an image to your next message)")
                continue
            path = Path(parts[1]).expanduser()
            if not path.exists() or not path.is_file():
                ui.error(f"Image not found: {parts[1]}")
                continue
            pending_images.append(str(path))
            ui.info(f"Attached image ({len(pending_images)} pending): {path}")
            continue
        if stripped == "/clear-img":
            pending_images.clear()
            ui.info("Cleared pending images.")
            continue
        if stripped == "/plan":
            plan_next_turn = True
            ui.info("Next turn will run in plan-generate mode.")
            continue

        images = pending_images.copy() if pending_images else None
        pending_images.clear()

        if plan_next_turn:
            plan_next_turn = False
            try:
                run_orchestrated(
                    client=client,
                    registry=registry,
                    session=session,
                    tools=tools,
                    allow_all=config.allow_all,
                    context_limit=config.context_limit,
                    user_input=user_input,
                    interactive=True,
                )
            except ConnectionError as e:
                ui.error(f"Beacon flickering. {e}")
            except KeyboardInterrupt:
                ui.warning("Interrupted.")
            continue

        user_msg = Message(role=Role.USER, content=user_input, images=images)
        session.append(user_msg)

        try:
            _run_agentic_loop(client, registry, session, tools, config.allow_all, config.context_limit)
        except ConnectionError as e:
            ui.error(f"Beacon flickering. {e}")
        except KeyboardInterrupt:
            ui.warning("Interrupted.")


def _run_agentic_loop(
    client: OllamaClient,
    registry: "ToolRegistry",
    session: Session,
    tools: list[dict[str, Any]],
    allow_all: bool,
    context_limit: int = 32768,
) -> None:
    from beaconhill.tools import ToolRegistry  # for type only

    run_agentic_loop(
        client=client,
        registry=registry,
        session=session,
        tools=tools,
        allow_all=allow_all,
        context_limit=context_limit,
        max_iterations=MAX_ITERATIONS,
    )
