import json
from argparse import Namespace
from pathlib import Path

import pytest

from beaconhill.config import (
    PLAN_MODE_ALWAYS,
    PLAN_MODE_AUTO,
    PLAN_MODE_NEVER,
    Config,
    should_plan,
)


class TestConfigDefaults:
    def test_default_values(self):
        config = Config()
        assert config.model == "gemma4:26b"
        assert config.host == "http://localhost:11434"
        assert config.session_dir is None
        assert config.allow_all is False
        assert config.context_limit == 32768
        assert config.plan_mode == PLAN_MODE_AUTO
        assert config.max_eval_iterations == 3
        assert config.plan_approval is True
        assert config.evaluator_tools == ["read_file", "glob", "grep"]


class TestConfigLoad:
    def test_load_no_config_files(self, tmp_path: Path):
        config = Config.load(project_dir=tmp_path)
        assert config.model == "gemma4:26b"

    def test_load_project_config(self, tmp_path: Path):
        config_dir = tmp_path / ".beaconhill"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(json.dumps({
            "model": "custom-model:7b",
            "allow_all": True,
        }))
        config = Config.load(project_dir=tmp_path)
        assert config.model == "custom-model:7b"
        assert config.allow_all is True
        # Unchanged defaults
        assert config.host == "http://localhost:11434"

    def test_load_ignores_unknown_keys(self, tmp_path: Path):
        config_dir = tmp_path / ".beaconhill"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(json.dumps({
            "unknown_key": "should be ignored",
            "model": "test:1b",
        }))
        config = Config.load(project_dir=tmp_path)
        assert config.model == "test:1b"
        assert not hasattr(config, "unknown_key")

    def test_load_none_project_dir(self):
        config = Config.load(project_dir=None)
        assert config.model == "gemma4:26b"


class TestConfigMerge:
    def test_merge_partial(self):
        config = Config()
        config._merge({"model": "merged-model"})
        assert config.model == "merged-model"
        assert config.host == "http://localhost:11434"

    def test_merge_all_fields(self):
        config = Config()
        config._merge({
            "model": "new-model",
            "host": "http://other:9999",
            "session_dir": "/tmp/sessions",
            "allow_all": True,
            "context_limit": 4096,
        })
        assert config.model == "new-model"
        assert config.host == "http://other:9999"
        assert config.session_dir == "/tmp/sessions"
        assert config.allow_all is True
        assert config.context_limit == 4096


class TestConfigCLIOverrides:
    def _make_args(self, **kwargs):
        defaults = {
            "model": "gemma4:26b",
            "host": "http://localhost:11434",
            "session_dir": None,
            "allow_all": False,
        }
        defaults.update(kwargs)
        return Namespace(**defaults)

    def test_no_overrides(self):
        config = Config(model="from-config")
        config.apply_cli_overrides(self._make_args())
        assert config.model == "from-config"

    def test_model_override(self):
        config = Config()
        config.apply_cli_overrides(self._make_args(model="cli-model"))
        assert config.model == "cli-model"

    def test_host_override(self):
        config = Config()
        config.apply_cli_overrides(self._make_args(host="http://custom:1234"))
        assert config.host == "http://custom:1234"

    def test_session_dir_override(self):
        config = Config()
        config.apply_cli_overrides(self._make_args(session_dir="/tmp/test"))
        assert config.session_dir == "/tmp/test"

    def test_allow_all_override(self):
        config = Config()
        config.apply_cli_overrides(self._make_args(allow_all=True))
        assert config.allow_all is True

    def test_default_args_dont_override_config(self):
        config = Config(model="config-model", host="http://config:5555")
        config.apply_cli_overrides(self._make_args())
        assert config.model == "config-model"
        assert config.host == "http://config:5555"

    def test_plan_flag_forces_always(self):
        config = Config()
        config.apply_cli_overrides(self._make_args(plan=True))
        assert config.plan_mode == PLAN_MODE_ALWAYS

    def test_plan_mode_override(self):
        config = Config()
        config.apply_cli_overrides(self._make_args(plan_mode="never"))
        assert config.plan_mode == PLAN_MODE_NEVER

    def test_invalid_plan_mode_raises(self):
        config = Config()
        with pytest.raises(ValueError):
            config.apply_cli_overrides(self._make_args(plan_mode="bogus"))


class TestShouldPlan:
    def test_always_bypasses_heuristic(self):
        assert should_plan("trivial", PLAN_MODE_ALWAYS) is True

    def test_never_bypasses_heuristic(self):
        assert (
            should_plan(
                "Refactor the auth module and then update the database schema and all the tests and then deploy after that",
                PLAN_MODE_NEVER,
            )
            is False
        )

    def test_auto_short_simple_prompt(self):
        assert should_plan("What time is it?", PLAN_MODE_AUTO) is False

    def test_auto_long_prompt(self):
        long_prompt = "x " * 150
        assert should_plan(long_prompt, PLAN_MODE_AUTO) is True

    def test_auto_multi_step_keyword(self):
        assert should_plan("Fix the bug and then add a test", PLAN_MODE_AUTO) is True

    def test_auto_refactor_keyword(self):
        assert should_plan("Refactor the auth module", PLAN_MODE_AUTO) is True

    def test_auto_simple_read_is_not_planned(self):
        assert should_plan("Read config.py", PLAN_MODE_AUTO) is False
