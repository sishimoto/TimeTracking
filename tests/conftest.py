"""
テスト共通フィクスチャ
"""

import os
import tempfile
import shutil

import pytest
import yaml


@pytest.fixture
def tmp_data_dir(tmp_path):
    """テスト用の一時データディレクトリ"""
    data_dir = tmp_path / ".timereaper"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def sample_config(tmp_data_dir):
    """テスト用の設定辞書"""
    return {
        "monitor": {"interval_seconds": 5, "idle_threshold_seconds": 300},
        "logging": {"level": "INFO"},
        "database": {"path": str(tmp_data_dir / "timereaper.db")},
        "dashboard": {"port": 5555, "host": "127.0.0.1"},
        "browser_apps": ["Google Chrome", "Safari", "Firefox"],
        "classification_rules": {
            "default_project_type": "カスタム開発",
            "project_types": [
                {
                    "type": "カスタム開発",
                    "keywords": ["impulse-pj-"],
                    "cost_category": "Impulse個別開発",
                },
                {
                    "type": "プロダクト開発",
                    "keywords": [r"(?<!-pj-)\bimpulse\b(?!-pj-)"],
                    "cost_category": "Impulse製品開発（共通機能の改良・強化）",
                },
            ],
            "sub_phases": {
                "テスト": {
                    "keywords": ["pytest", "unittest", "test.*result"],
                    "match_target": "search_text",
                },
                "設計": {
                    "keywords": ["Figma", "Sketch", "Miro"],
                    "match_target": "app_name",
                },
                "実装": {
                    "keywords": [
                        "Visual Studio Code",
                        "IntelliJ",
                        "Terminal",
                        "Cursor",
                    ],
                    "match_target": "app_name",
                },
            },
            "standalone_phases": {
                "meeting": {
                    "keywords": ["Zoom", "Google Meet", "Slack"],
                },
                "email": {
                    "keywords": ["Mail", "Gmail", "Outlook"],
                },
                "documentation": {
                    "keywords": ["Notion", "Confluence"],
                },
                "planning": {
                    "keywords": ["Jira", "Linear"],
                },
                "research": {
                    "keywords": ["stackoverflow\\.com", "qiita\\.com"],
                },
            },
            "slack_channel_rules": [
                {
                    "channels": ["general", "random"],
                    "project": "全社活動",
                },
            ],
            "calendar_work_patterns": ["開発$", "^work$"],
            "calendar_other_patterns": ["お昼", "昼食", "ランチ", "休暇"],
            "calendar_project_rules": [
                {
                    "keywords": ["全社", "全体会", "朝会", "定例"],
                    "project": "全社活動",
                },
            ],
            "cost_categories": [
                "Impulse個別開発",
                "Impulse製品開発（共通機能の改良・強化）",
                "全社活動",
            ],
            "task_categories": [
                "分析", "要件定義", "設計", "実装", "テスト",
                "meeting", "email", "documentation", "planning", "research",
            ],
        },
        "mac_calendar": {"enabled": False},
        "google_calendar": {"enabled": False},
        "slack": {"enabled": False},
    }


@pytest.fixture
def config_file(tmp_path, sample_config):
    """テスト用の config.yaml ファイルを作成"""
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_config, f, allow_unicode=True, default_flow_style=False)
    return str(config_path)
