import os
from io import StringIO
from unittest.mock import patch

from beaconhill.ui import (
    ThinkingPulse,
    _use_color,
    amber,
    bold,
    bold_amber,
    green,
    grey,
    red,
    summarize_args,
)


class TestUseColor:
    def test_no_color_env_disables(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            assert _use_color() is False

    def test_non_tty_disables(self):
        with patch.dict(os.environ, {}, clear=True):
            # In tests, stdout is not a TTY
            if not os.environ.get("NO_COLOR"):
                assert _use_color() is False


class TestColorFunctions:
    def test_amber_no_color(self):
        with patch("beaconhill.ui._use_color", return_value=False):
            assert amber("test") == "test"

    def test_amber_with_color(self):
        with patch("beaconhill.ui._use_color", return_value=True):
            result = amber("test")
            assert "\033[33m" in result
            assert "\033[0m" in result
            assert "test" in result

    def test_green_no_color(self):
        with patch("beaconhill.ui._use_color", return_value=False):
            assert green("test") == "test"

    def test_green_with_color(self):
        with patch("beaconhill.ui._use_color", return_value=True):
            result = green("test")
            assert "\033[32m" in result

    def test_red_no_color(self):
        with patch("beaconhill.ui._use_color", return_value=False):
            assert red("test") == "test"

    def test_red_with_color(self):
        with patch("beaconhill.ui._use_color", return_value=True):
            result = red("test")
            assert "\033[31m" in result

    def test_grey_no_color(self):
        with patch("beaconhill.ui._use_color", return_value=False):
            assert grey("test") == "test"

    def test_grey_with_color(self):
        with patch("beaconhill.ui._use_color", return_value=True):
            result = grey("test")
            assert "\033[90m" in result

    def test_bold_no_color(self):
        with patch("beaconhill.ui._use_color", return_value=False):
            assert bold("test") == "test"

    def test_bold_amber_with_color(self):
        with patch("beaconhill.ui._use_color", return_value=True):
            result = bold_amber("test")
            assert "\033[1m" in result
            assert "\033[33m" in result


class TestSummarizeArgs:
    def test_command_arg(self):
        assert summarize_args({"command": "ls -la"}) == "ls -la"

    def test_file_path_arg(self):
        assert summarize_args({"file_path": "src/main.py"}) == "src/main.py"

    def test_pattern_arg(self):
        assert summarize_args({"pattern": "**/*.py"}) == "**/*.py"

    def test_command_takes_precedence(self):
        result = summarize_args({"command": "ls", "file_path": "test"})
        assert result == "ls"

    def test_fallback_to_json(self):
        result = summarize_args({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result


class TestBrandedOutput:
    """Test that branded output functions produce expected content."""

    def test_banner(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import banner
            banner("gemma4:26b", "abcd1234-5678-9012-3456")
            output = capsys.readouterr().out
            assert "Beaconhill" in output
            assert "Beacon lit" in output
            assert "gemma4:26b" in output
            assert "abcd1234" in output
            assert "/quit" in output

    def test_banner_resumed(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import banner
            banner("gemma4:26b", "abcd1234", resumed=True, msg_count=10)
            output = capsys.readouterr().out
            assert "10 messages resumed" in output

    def test_banner_oneshot(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import banner_oneshot
            banner_oneshot("gemma4:26b")
            output = capsys.readouterr().out
            assert "Beaconhill" in output
            assert "gemma4:26b" in output

    def test_goodbye(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import goodbye
            goodbye()
            output = capsys.readouterr().out
            assert "Beacon extinguished" in output

    def test_tool_start(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import tool_start
            tool_start("read_file", "src/main.py")
            output = capsys.readouterr().out
            assert "read_file" in output
            assert "src/main.py" in output
            assert "---" in output

    def test_tool_end(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import tool_end
            tool_end()
            output = capsys.readouterr().out
            assert "---" in output

    def test_tool_error(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import tool_error
            tool_error("something failed")
            output = capsys.readouterr().out
            assert "something failed" in output

    def test_tool_denied(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import tool_denied
            tool_denied("bash")
            output = capsys.readouterr().out
            assert "bash" in output
            assert "denied" in output

    def test_tool_denied_by_user(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import tool_denied
            tool_denied("bash", by_user=True)
            output = capsys.readouterr().out
            assert "by user" in output

    def test_info(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import info
            info("status message")
            output = capsys.readouterr().out
            assert "status message" in output

    def test_error(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import error
            error("error message")
            output = capsys.readouterr().out
            assert "error message" in output

    def test_warning(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import warning
            warning("warning message")
            output = capsys.readouterr().out
            assert "warning message" in output

    def test_token_count(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import token_count
            token_count(1500, 32768)
            output = capsys.readouterr().out
            assert "1500" in output
            assert "32768" in output


class TestReplayOutput:
    def test_replay_header(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import replay_header
            replay_header("abcd1234-full-id", "2026-01-01", "gemma4:26b")
            output = capsys.readouterr().out
            assert "abcd1234" in output
            assert "gemma4:26b" in output

    def test_replay_user(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import replay_user
            replay_user("hello world")
            output = capsys.readouterr().out
            assert ">>>" in output
            assert "hello world" in output

    def test_replay_tool_output_truncation(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import replay_tool_output
            long_text = "x" * 300
            replay_tool_output(long_text)
            output = capsys.readouterr().out
            assert "..." in output
            assert len(output) < 300

    def test_replay_footer(self, capsys):
        with patch("beaconhill.ui._use_color", return_value=False):
            from beaconhill.ui import replay_footer
            replay_footer()
            output = capsys.readouterr().out
            assert "end of session" in output


class TestThinkingPulse:
    def test_start_stop_non_tty(self):
        # In tests, stdout is not a TTY, so pulse should be a no-op
        pulse = ThinkingPulse()
        pulse.start()
        assert pulse._thread is None  # should not start in non-TTY
        pulse.stop()

    def test_custom_label(self):
        pulse = ThinkingPulse(label="running bash")
        assert pulse._label == "running bash"

    def test_stop_without_start(self):
        pulse = ThinkingPulse()
        pulse.stop()  # should not raise
