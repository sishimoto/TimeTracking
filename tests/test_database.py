"""
database.py のユニットテスト
"""

import sqlite3
import os
from datetime import datetime, date, timedelta
from unittest.mock import patch

import pytest

from timereaper.config import load_config, get_config


class TestDatabase:
    """database.py のテスト"""

    @pytest.fixture(autouse=True)
    def setup_db(self, config_file, tmp_data_dir):
        """テスト用に設定を読み込み DB を初期化"""
        load_config(config_file)
        from timereaper.database import init_db, get_db_path
        init_db()
        self.db_path = get_db_path()

    def test_init_db_creates_file(self):
        """init_db で DB ファイルが作成される"""
        assert os.path.exists(self.db_path)

    def test_activity_log_table_exists(self):
        """activity_log テーブルが作成されている"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_log'"
        )
        assert c.fetchone() is not None
        conn.close()

    def test_calendar_events_table_exists(self):
        """calendar_events テーブルが作成されている"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='calendar_events'"
        )
        assert c.fetchone() is not None
        conn.close()

    def test_insert_and_get_activity(self):
        """アクティビティの挿入と取得"""
        from timereaper.database import insert_activity, get_connection

        insert_activity(
            timestamp="2024-01-01T10:00:00",
            app_name="Visual Studio Code",
            window_title="main.py",
            bundle_id="com.microsoft.VSCode",
            url="",
            duration_seconds=5.0,
            is_idle=False,
            project="Impulse個別開発",
            work_phase="実装",
            category="development",
        )

        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT app_name, project, work_phase FROM activity_log")
            row = c.fetchone()
            assert row is not None
            assert row[0] == "Visual Studio Code"
            assert row[1] == "Impulse個別開発"
            assert row[2] == "実装"

    def test_insert_activity_with_tab_title(self):
        """tab_title 付きでアクティビティを挿入"""
        from timereaper.database import insert_activity, get_connection

        insert_activity(
            timestamp="2024-01-01T10:00:05",
            app_name="Google Chrome",
            window_title="GitHub - main",
            bundle_id="com.google.Chrome",
            url="https://github.com/owner/repo",
            duration_seconds=5.0,
            is_idle=False,
            project="",
            work_phase="research",
            category="browser",
            tab_title="GitHub Pull Requests",
        )

        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT tab_title FROM activity_log WHERE app_name='Google Chrome'")
            row = c.fetchone()
            assert row is not None
            assert row[0] == "GitHub Pull Requests"

    def test_get_daily_summary(self):
        """日次サマリーの取得"""
        from timereaper.database import insert_activity, get_daily_summary

        # 複数アクティビティを挿入
        for i in range(3):
            insert_activity(
                timestamp=f"2024-01-15T10:0{i}:00",
                app_name="Visual Studio Code",
                window_title="main.py",
                bundle_id="com.microsoft.VSCode",
                url="",
                duration_seconds=60.0,
                is_idle=False,
                project="Impulse個別開発",
                work_phase="実装",
                category="development",
            )
        insert_activity(
            timestamp="2024-01-15T11:00:00",
            app_name="Slack",
            window_title="general",
            bundle_id="com.tinyspeck.slackmacgap",
            url="",
            duration_seconds=30.0,
            is_idle=False,
            project="全社活動",
            work_phase="meeting",
            category="communication",
        )

        summary = get_daily_summary("2024-01-15")
        assert isinstance(summary, list)
        assert len(summary) >= 2  # VS Code + Slack
        total = sum(row["total_seconds"] for row in summary)
        assert total > 0
        app_names = [row["app_name"] for row in summary]
        assert "Visual Studio Code" in app_names
        assert "Slack" in app_names

    def test_get_daily_summary_no_data(self):
        """データなしの日はサマリーが空リスト"""
        from timereaper.database import get_daily_summary

        summary = get_daily_summary("2099-12-31")
        assert isinstance(summary, list)
        assert len(summary) == 0

    def test_get_activities_by_date(self):
        """日付指定でアクティビティを取得"""
        from timereaper.database import insert_activity, get_activities

        insert_activity(
            timestamp="2024-06-01T09:00:00",
            app_name="Terminal",
            window_title="bash",
            bundle_id="com.apple.Terminal",
            url="",
            duration_seconds=10.0,
            is_idle=False,
            project="",
            work_phase="実装",
            category="development",
        )

        activities = get_activities("2024-06-01")
        assert len(activities) > 0
        assert activities[0]["app_name"] == "Terminal"

    def test_get_connection_context_manager(self):
        """get_connection がコンテキストマネージャーとして機能する"""
        from timereaper.database import get_connection

        with get_connection() as conn:
            assert conn is not None
            c = conn.cursor()
            c.execute("SELECT 1")
            assert c.fetchone()[0] == 1
