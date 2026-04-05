from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from beaconhill.agent import MAX_ITERATIONS, build_system_prompt
from beaconhill.client import OllamaClient
from beaconhill.config import Config
from beaconhill.context import compact_messages, estimate_tokens, needs_compaction
from beaconhill.models import Message, Role
from beaconhill.session import DEFAULT_SESSION_DIR, Session
from beaconhill.tools import Policy, create_default_registry


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
    return parser.parse_args()


def format_tool_call(name: str, arguments: dict[str, Any]) -> str:
    """Format a tool call for display to the user."""
    args_str = json.dumps(arguments, indent=2, ensure_ascii=False)
    return f"[tool] {name}\n{args_str}"


def prompt_user_permission(name: str, arguments: dict[str, Any]) -> bool:
    """Ask the user whether to allow a tool call. Returns True if allowed."""
    print(f"\n{format_tool_call(name, arguments)}")
    try:
        answer = input("Allow? [y/N] ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    return answer in ("y", "yes")


def _resolve_session_path(ref: str, session_dir: Path | None = None) -> Path:
    """Resolve a session reference (path or ID) to a file path."""
    p = Path(ref)
    if p.exists():
        return p
    dir_ = session_dir or DEFAULT_SESSION_DIR
    candidate = dir_ / f"{ref}.jsonl"
    if candidate.exists():
        return candidate
    # Try partial match
    if dir_.exists():
        matches = sorted(dir_.glob(f"{ref}*.jsonl"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(f"Ambiguous session ID, matches: {[m.stem for m in matches]}")
            sys.exit(1)
    print(f"Session not found: {ref}")
    sys.exit(1)


def _replay_session(path: Path) -> None:
    """Display a past session read-only."""
    session = Session.load(path)
    print(f"Replaying session: {session.meta.session_id}")
    print(f"Created: {session.meta.created_at} | Model: {session.meta.model}")
    print("-" * 60)
    for msg in session.messages:
        if msg.role == Role.SYSTEM:
            continue
        if msg.role == Role.USER:
            print(f"\n>>> {msg.content}")
        elif msg.role == Role.ASSISTANT:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"[tool] {tc.name}: {_summarize_args(tc.arguments)}")
            if msg.content:
                print(msg.content)
        elif msg.role == Role.TOOL:
            # Show truncated tool output
            content = msg.content or ""
            if len(content) > 200:
                content = content[:200] + "..."
            print(f"  -> {content}")
    print(f"\n{'─' * 60}")
    print("(end of session)")


def main() -> None:
    args = parse_args()

    # Load config: defaults < global < project < CLI args
    config = Config.load(project_dir=Path.cwd())
    config.apply_cli_overrides(args)

    session_dir = Path(config.session_dir) if config.session_dir else None

    # Handle --replay (read-only, no Ollama needed)
    if args.replay:
        path = _resolve_session_path(args.replay, session_dir)
        _replay_session(path)
        return

    client = OllamaClient(model=config.model, host=config.host)
    registry = create_default_registry()

    # Handle --resume or new session
    if args.resume:
        path = _resolve_session_path(args.resume, session_dir)
        session = Session.load(path)
        print(f"beaconhill v0.1.0 | model: {config.model}")
        print(f"Resumed session: {session.meta.session_id}")
        print(f"  {len(session.messages)} messages loaded")
        print("Type /quit to exit.\n")
    else:
        session = Session(model=config.model, session_dir=session_dir)
        print(f"beaconhill v0.1.0 | model: {config.model}")
        print(f"session: {session.path}")
        print("Type /quit to exit.\n")
        system_msg = Message(role=Role.SYSTEM, content=build_system_prompt())
        session.append(system_msg)

    tools = registry.to_ollama()

    # One-shot mode
    if args.prompt:
        user_msg = Message(role=Role.USER, content=args.prompt)
        session.append(user_msg)
        try:
            _run_agentic_loop(client, registry, session, tools, allow_all=config.allow_all)
        except ConnectionError as e:
            print(f"[error] {e}", file=sys.stderr)
            sys.exit(1)
        return

    while True:
        try:
            user_input = input(">>> ")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        stripped = user_input.strip()
        if not stripped:
            continue
        if stripped in ("/quit", "/exit"):
            print("Goodbye.")
            break
        if stripped == "/session":
            print(f"Session: {session.path}")
            continue

        user_msg = Message(role=Role.USER, content=user_input)
        session.append(user_msg)

        try:
            _run_agentic_loop(client, registry, session, tools, config.allow_all)
        except ConnectionError as e:
            print(f"\n[error] {e}")
        except KeyboardInterrupt:
            print("\n[interrupted]")


def _run_agentic_loop(
    client: OllamaClient,
    registry: "ToolRegistry",
    session: Session,
    tools: list[dict[str, Any]],
    allow_all: bool,
) -> None:
    """Run the agentic loop: LLM -> tool calls -> repeat until done."""
    from beaconhill.tools import ToolRegistry  # for type only

    for _ in range(MAX_ITERATIONS):
        # Compact if approaching context limit
        if needs_compaction(session.messages, client=client):
            print("[compacting context...]")
            session.messages = compact_messages(session.messages, client)

        response, text_stream = client.chat_or_stream(session.messages, tools=tools)

        if text_stream is not None:
            # Final text response -- stream to display
            chunks: list[str] = []
            for chunk in text_stream:
                print(chunk, end="", flush=True)
                chunks.append(chunk)
            print()
            full_text = "".join(chunks) or None
            session.append(Message(role=Role.ASSISTANT, content=full_text))
            return

        # Tool-calling turn
        session.append(response)

        # Process tool calls
        for tc in response.tool_calls:
            policy = registry.check_permission(tc.name)

            if policy == Policy.DENY:
                print(f"[denied] {tc.name}")
                tool_msg = Message(
                    role=Role.TOOL,
                    content="Permission denied",
                    tool_call_id=tc.name,
                )
                session.append(tool_msg)
                continue

            if policy == Policy.ASK and not allow_all:
                allowed = prompt_user_permission(tc.name, tc.arguments)
                if not allowed:
                    print(f"[denied by user] {tc.name}")
                    tool_msg = Message(
                        role=Role.TOOL,
                        content="Permission denied by user",
                        tool_call_id=tc.name,
                    )
                    session.append(tool_msg)
                    continue
            else:
                # ALLOW or --allow-all: show what's running
                print(f"[tool] {tc.name}: {_summarize_args(tc.arguments)}")

            result = registry.execute(tc.name, tc.arguments)
            if result.is_error:
                print(f"[error] {result.output}")

            tool_msg = Message(
                role=Role.TOOL,
                content=result.output,
                tool_call_id=tc.name,
            )
            session.append(tool_msg)

    print("[warning] Max iterations reached.")


def _summarize_args(arguments: dict[str, Any]) -> str:
    """One-line summary of tool arguments for display."""
    if "command" in arguments:
        return arguments["command"]
    if "file_path" in arguments:
        return arguments["file_path"]
    if "pattern" in arguments:
        return arguments["pattern"]
    return json.dumps(arguments, ensure_ascii=False)
