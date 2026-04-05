from __future__ import annotations

import enum
import glob as glob_module
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class Permission(enum.StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


class Policy(enum.StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


DEFAULT_POLICIES: dict[Permission, Policy] = {
    Permission.READ: Policy.ALLOW,
    Permission.WRITE: Policy.ASK,
    Permission.EXECUTE: Policy.ASK,
}


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    required_permission: Permission
    fn: Callable[[dict[str, Any]], str]

    def to_ollama(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    output: str
    is_error: bool = False


class ToolRegistry:
    def __init__(
        self,
        policies: dict[Permission, Policy] | None = None,
    ) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._policies = policies or dict(DEFAULT_POLICIES)

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def to_ollama(self) -> list[dict[str, Any]]:
        return [spec.to_ollama() for spec in self._tools.values()]

    def check_permission(self, name: str) -> Policy:
        spec = self._tools.get(name)
        if spec is None:
            return Policy.DENY
        return self._policies.get(spec.required_permission, Policy.ASK)

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(output=f"Unknown tool: {name}", is_error=True)
        try:
            output = spec.fn(arguments)
            return ToolResult(output=output)
        except Exception as e:
            return ToolResult(output=f"Error: {e}", is_error=True)


# --- Core tool implementations ---


MAX_TOOL_OUTPUT = 10_000


def _bash(args: dict[str, Any]) -> str:
    command = args["command"]
    timeout = args.get("timeout", 30)
    max_output = args.get("max_output", MAX_TOOL_OUTPUT)
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    if result.returncode != 0:
        output += f"\n[exit code: {result.returncode}]"
    output = output.strip()
    if len(output) > max_output:
        output = output[:max_output] + f"\n[truncated at {max_output} chars]"
    return output


def _read_file(args: dict[str, Any]) -> str:
    path = Path(args["file_path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    offset = args.get("offset", 0)
    limit = args.get("limit")
    lines = path.read_text().splitlines()
    if limit is not None:
        lines = lines[offset:offset + limit]
    else:
        lines = lines[offset:]
    numbered = [f"{i + offset + 1}\t{line}" for i, line in enumerate(lines)]
    return "\n".join(numbered)


def _write_file(args: dict[str, Any]) -> str:
    path = Path(args["file_path"])
    content = args["content"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"Wrote {len(content)} bytes to {path}"


def _edit_file(args: dict[str, Any]) -> str:
    path = Path(args["file_path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    old = args["old_string"]
    new = args["new_string"]
    text = path.read_text()
    count = text.count(old)
    if count == 0:
        raise ValueError(f"old_string not found in {path}")
    text = text.replace(old, new, 1)
    path.write_text(text)
    return f"Replaced 1 occurrence in {path}"


def _glob(args: dict[str, Any]) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    matches = sorted(glob_module.glob(os.path.join(path, pattern), recursive=True))
    if not matches:
        return "No files found"
    return "\n".join(matches)


def _grep(args: dict[str, Any]) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    include = args.get("glob")
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}")

    results: list[str] = []
    search_path = Path(path)

    if search_path.is_file():
        files = [search_path]
    else:
        glob_pattern = include or "**/*"
        files = [f for f in search_path.glob(glob_pattern) if f.is_file()]

    for file in sorted(files):
        try:
            for i, line in enumerate(file.read_text().splitlines(), 1):
                if regex.search(line):
                    results.append(f"{file}:{i}:{line}")
        except (UnicodeDecodeError, PermissionError):
            continue

    if not results:
        return "No matches found"
    return "\n".join(results[:100])


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(ToolSpec(
        name="bash",
        description="Run a shell command and return stdout/stderr.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
            },
            "required": ["command"],
        },
        required_permission=Permission.EXECUTE,
        fn=_bash,
    ))

    registry.register(ToolSpec(
        name="read_file",
        description="Read a file's contents with line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute or relative path to the file"},
                "offset": {"type": "integer", "description": "Line number to start from (0-based)"},
                "limit": {"type": "integer", "description": "Number of lines to read"},
            },
            "required": ["file_path"],
        },
        required_permission=Permission.READ,
        fn=_read_file,
    ))

    registry.register(ToolSpec(
        name="write_file",
        description="Create or overwrite a file with the given content.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["file_path", "content"],
        },
        required_permission=Permission.WRITE,
        fn=_write_file,
    ))

    registry.register(ToolSpec(
        name="edit_file",
        description="Replace the first occurrence of old_string with new_string in a file.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to edit"},
                "old_string": {"type": "string", "description": "Text to find"},
                "new_string": {"type": "string", "description": "Text to replace it with"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
        required_permission=Permission.WRITE,
        fn=_edit_file,
    ))

    registry.register(ToolSpec(
        name="glob",
        description="Find files matching a glob pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.py')"},
                "path": {"type": "string", "description": "Directory to search in (default: current directory)"},
            },
            "required": ["pattern"],
        },
        required_permission=Permission.READ,
        fn=_glob,
    ))

    registry.register(ToolSpec(
        name="grep",
        description="Search file contents with a regex pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "File or directory to search (default: current directory)"},
                "glob": {"type": "string", "description": "Glob filter for files (e.g., '*.py')"},
            },
            "required": ["pattern"],
        },
        required_permission=Permission.READ,
        fn=_grep,
    ))

    return registry
