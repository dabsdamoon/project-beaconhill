from __future__ import annotations

import os
from pathlib import Path

from beaconhill.client import OllamaClient
from beaconhill.models import Message, Role, ToolCall
from beaconhill.tools import ToolRegistry, ToolResult

MAX_ITERATIONS = 50


def build_system_prompt(working_dir: str | None = None) -> str:
    cwd = working_dir or os.getcwd()
    # Gather top-level file listing for project context
    try:
        entries = sorted(Path(cwd).iterdir())
        listing = "\n".join(
            f"  {'[dir] ' if e.is_dir() else ''}{e.name}" for e in entries[:30]
        )
    except OSError:
        listing = "  (unable to list directory)"

    return f"""\
You are Beaconhill, a local-first coding assistant running on the developer's machine.

## Role
You help developers read, write, search, and reason about code. You have access to \
tools for file operations and shell commands. Use them to accomplish tasks.

## Behavior
- Be concise and direct. No filler.
- Use tools to verify assumptions rather than guessing.
- When editing code, read the file first to understand context.
- When asked to fix a bug, read the relevant code and tests before making changes.
- If a task requires multiple steps, chain tool calls until done.
- Do not make changes beyond what was asked.

## Working Directory
{cwd}

## Project Files
{listing}
"""


def run_agent_turn(
    user_prompt: str,
    client: OllamaClient,
    registry: ToolRegistry,
    messages: list[Message] | None = None,
) -> tuple[list[Message], str]:
    """Run one agentic turn: prompt -> tool loop -> final response.

    Returns the full message history and the final assistant text.
    """
    if messages is None:
        messages = [Message(role=Role.SYSTEM, content=build_system_prompt())]

    messages.append(Message(role=Role.USER, content=user_prompt))
    tools = registry.to_ollama()

    for _ in range(MAX_ITERATIONS):
        response = client.chat(messages, tools=tools)
        messages.append(response)

        if not response.tool_calls:
            return messages, response.content or ""

        for tc in response.tool_calls:
            result = registry.execute(tc.name, tc.arguments)
            tool_msg = Message(
                role=Role.TOOL,
                content=result.output,
                tool_call_id=tc.name,
            )
            messages.append(tool_msg)

    # Safety: if we hit max iterations, return whatever we have
    last_text = ""
    for m in reversed(messages):
        if m.role == Role.ASSISTANT and m.content:
            last_text = m.content
            break
    return messages, last_text
