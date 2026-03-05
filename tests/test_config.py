"""
config.py のユニットテスト
"""

import os
import yaml
import pytest

from timereaper.config import load_config, get_config, _config


class TestLoadConfig:
    """load_config() のテスト"""

    def test_load_valid_config(self, config_file):
        """正常な config.yaml を読み込めること"""
        cfg = load_config(config_file)
        assert isinstance(cfg, dict)
        assert "monitor" in cfg
        assert "database" in cfg
        assert cfg["monitor"]["interval_seconds"] == 5

    def test_load_config_expands_db_path(self, tmp_path):
        """database.path のチルダが展開されること"""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "database": {"path": "~/.timereaper/test.db"},
        }
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        cfg = load_config(str(config_path))
        assert "~" not in cfg["database"]["path"]
        assert cfg["database"]["path"].startswith("/")

    def test_load_missing_file_raises(self):
        """存在しないファイルで FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_load_config_returns_dict(self, config_file):
        """load_config の戻り値が dict であること"""
        result = load_config(config_file)
        assert isinstance(result, dict)

    def test_classification_rules_loaded(self, config_file):
        """classification_rules が正しく読み込まれること"""
        cfg = load_config(config_file)
        rules = cfg.get("classification_rules", {})
        assert "project_types" in rules
        assert "sub_phases" in rules
        assert "standalone_phases" in rules

    def test_logging_level_loaded(self, config_file):
        """logging.level が読み込まれること"""
        cfg = load_config(config_file)
        assert cfg["logging"]["level"] == "INFO"


class TestGetConfig:
    """get_config() のテスト"""

    def test_get_config_returns_cached(self, config_file):
        """get_config は load_config のキャッシュを返すこと"""
        # まず load_config で読み込む
        cfg = load_config(config_file)
        # get_config はキャッシュを返す
        cached = get_config()
        assert cached is cfg
