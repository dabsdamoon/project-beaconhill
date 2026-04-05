from __future__ import annotations

import os
from pathlib import Path

import pytest

from beaconhill.tools import (
    DEFAULT_POLICIES,
    MAX_TOOL_OUTPUT,
    Permission,
    Policy,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    _bash,
    _edit_file,
    _glob,
    _grep,
    _read_file,
    _write_file,
    create_default_registry,
)


class TestPermission:
    def test_default_policies(self):
        assert DEFAULT_POLICIES[Permission.READ] == Policy.ALLOW
        assert DEFAULT_POLICIES[Permission.WRITE] == Policy.ASK
        assert DEFAULT_POLICIES[Permission.EXECUTE] == Policy.ASK


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        spec = ToolSpec(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.READ,
            fn=lambda args: "ok",
        )
        registry.register(spec)
        assert registry.get("test_tool") is spec
        assert registry.get("nonexistent") is None

    def test_list_specs(self):
        registry = create_default_registry()
        specs = registry.list_specs()
        names = {s.name for s in specs}
        assert names == {"bash", "read_file", "write_file", "edit_file", "glob", "grep"}

    def test_to_ollama_format(self):
        registry = create_default_registry()
        ollama_tools = registry.to_ollama()
        assert len(ollama_tools) == 6
        for tool in ollama_tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    def test_check_permission_defaults(self):
        registry = create_default_registry()
        assert registry.check_permission("read_file") == Policy.ALLOW
        assert registry.check_permission("glob") == Policy.ALLOW
        assert registry.check_permission("grep") == Policy.ALLOW
        assert registry.check_permission("write_file") == Policy.ASK
        assert registry.check_permission("edit_file") == Policy.ASK
        assert registry.check_permission("bash") == Policy.ASK

    def test_check_permission_unknown_tool(self):
        registry = create_default_registry()
        assert registry.check_permission("nonexistent") == Policy.DENY

    def test_check_permission_custom_policies(self):
        registry = ToolRegistry(policies={
            Permission.READ: Policy.ALLOW,
            Permission.WRITE: Policy.ALLOW,
            Permission.EXECUTE: Policy.DENY,
        })
        spec = ToolSpec(
            name="dangerous",
            description="",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.EXECUTE,
            fn=lambda args: "ok",
        )
        registry.register(spec)
        assert registry.check_permission("dangerous") == Policy.DENY

    def test_execute_success(self):
        registry = ToolRegistry()
        registry.register(ToolSpec(
            name="echo",
            description="",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.READ,
            fn=lambda args: f"got: {args.get('msg', '')}",
        ))
        result = registry.execute("echo", {"msg": "hello"})
        assert result.output == "got: hello"
        assert result.is_error is False

    def test_execute_unknown_tool(self):
        registry = ToolRegistry()
        result = registry.execute("nonexistent", {})
        assert result.is_error is True
        assert "Unknown tool" in result.output

    def test_execute_catches_exception(self):
        registry = ToolRegistry()
        registry.register(ToolSpec(
            name="fail",
            description="",
            parameters={"type": "object", "properties": {}},
            required_permission=Permission.READ,
            fn=lambda args: (_ for _ in ()).throw(ValueError("boom")),
        ))
        result = registry.execute("fail", {})
        assert result.is_error is True
        assert "boom" in result.output


class TestBash:
    def test_simple_command(self):
        output = _bash({"command": "echo hello"})
        assert output == "hello"

    def test_exit_code_shown(self):
        output = _bash({"command": "exit 42"})
        assert "[exit code: 42]" in output

    def test_stderr_captured(self):
        output = _bash({"command": "echo err >&2"})
        assert "[stderr]" in output
        assert "err" in output

    def test_timeout(self):
        with pytest.raises(Exception):
            _bash({"command": "sleep 10", "timeout": 1})

    def test_output_truncation(self):
        # Generate output larger than MAX_TOOL_OUTPUT
        output = _bash({
            "command": f"python3 -c \"print('x' * {MAX_TOOL_OUTPUT + 1000})\"",
            "max_output": 500,
        })
        assert len(output) <= 600  # 500 + truncation message
        assert "[truncated at 500 chars]" in output


class TestReadFile:
    def test_read_full(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        output = _read_file({"file_path": str(f)})
        assert "1\tline1" in output
        assert "3\tline3" in output

    def test_read_with_offset_and_limit(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd\ne\n")
        output = _read_file({"file_path": str(f), "offset": 1, "limit": 2})
        lines = output.strip().splitlines()
        assert len(lines) == 2
        assert "2\tb" in lines[0]
        assert "3\tc" in lines[1]

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            _read_file({"file_path": "/nonexistent/file.txt"})


class TestWriteFile:
    def test_write_creates_file(self, tmp_path: Path):
        f = tmp_path / "new.txt"
        result = _write_file({"file_path": str(f), "content": "hello"})
        assert f.read_text() == "hello"
        assert "5 bytes" in result

    def test_write_creates_parent_dirs(self, tmp_path: Path):
        f = tmp_path / "sub" / "dir" / "file.txt"
        _write_file({"file_path": str(f), "content": "nested"})
        assert f.read_text() == "nested"


class TestEditFile:
    def test_replace_first_occurrence(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo baz")
        result = _edit_file({"file_path": str(f), "old_string": "foo", "new_string": "qux"})
        assert f.read_text() == "qux bar foo baz"
        assert "Replaced 1 occurrence" in result

    def test_old_string_not_found(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        with pytest.raises(ValueError, match="not found"):
            _edit_file({"file_path": str(f), "old_string": "xyz", "new_string": "abc"})

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            _edit_file({"file_path": "/nonexistent.txt", "old_string": "a", "new_string": "b"})


class TestGlob:
    def test_find_files(self, tmp_path: Path):
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "c.txt").touch()
        output = _glob({"pattern": "*.py", "path": str(tmp_path)})
        assert "a.py" in output
        assert "b.py" in output
        assert "c.txt" not in output

    def test_recursive(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.py").touch()
        output = _glob({"pattern": "**/*.py", "path": str(tmp_path)})
        assert "deep.py" in output

    def test_no_matches(self, tmp_path: Path):
        output = _glob({"pattern": "*.xyz", "path": str(tmp_path)})
        assert output == "No files found"


class TestGrep:
    def test_search_file(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("import os\nimport sys\nprint('hello')\n")
        output = _grep({"pattern": "import", "path": str(f)})
        assert "1:import os" in output
        assert "2:import sys" in output

    def test_search_directory(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("def foo(): pass\n")
        (tmp_path / "b.py").write_text("def bar(): pass\n")
        output = _grep({"pattern": "def \\w+", "path": str(tmp_path)})
        assert "a.py" in output
        assert "b.py" in output

    def test_glob_filter(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("match\n")
        (tmp_path / "b.txt").write_text("match\n")
        output = _grep({"pattern": "match", "path": str(tmp_path), "glob": "*.py"})
        assert "a.py" in output
        assert "b.txt" not in output

    def test_no_matches(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("nothing here\n")
        output = _grep({"pattern": "xyz123", "path": str(tmp_path)})
        assert output == "No matches found"

    def test_invalid_regex(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Invalid regex"):
            _grep({"pattern": "[invalid", "path": str(tmp_path)})

    def test_skips_binary_files(self, tmp_path: Path):
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\xff" * 100)
        output = _grep({"pattern": "test", "path": str(tmp_path)})
        assert output == "No matches found"
