"""
migration.py のユニットテスト
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from timereaper.config import load_config


class TestMigration:
    """ローカル移行（export/import）のテスト"""

    @pytest.fixture(autouse=True)
    def setup_env(self, config_file, tmp_data_dir, monkeypatch):
        load_config(config_file)

        # user_settings.json の書き込み先をテスト用ディレクトリに寄せる
        import timereaper.user_settings as user_settings

        monkeypatch.setattr(user_settings, "_SETTINGS_PATH", tmp_data_dir / "user_settings.json")
        monkeypatch.setattr(user_settings, "_settings", None)

        from timereaper.database import init_db

        init_db()
        self.data_dir = tmp_data_dir

    def test_create_migration_archive_contains_expected_files(self, tmp_path):
        from timereaper.database import insert_activity
        from timereaper.migration import (
            ARCHIVE_FORMAT_VERSION,
            CONFIG_ARCHIVE_NAME,
            DB_ARCHIVE_NAME,
            MANIFEST_NAME,
            SETTINGS_ARCHIVE_NAME,
            create_migration_archive,
        )
        from timereaper.user_settings import save_user_settings

        insert_activity(
            timestamp="2026-03-01T10:00:00",
            app_name="Visual Studio Code",
            window_title="main.py",
            duration_seconds=60.0,
            is_idle=False,
            project="個人開発",
            work_phase="実装",
            category="development",
        )
        save_user_settings({"pomodoro": {"enabled": True, "work_minutes": 50}})
        (self.data_dir / "google_token.json").write_text('{"token":"dummy"}', encoding="utf-8")

        archive = tmp_path / "migration.zip"
        output = create_migration_archive(output_path=str(archive), include_config=True)
        assert Path(output).exists()

        with zipfile.ZipFile(output, "r") as zf:
            names = set(zf.namelist())
            assert MANIFEST_NAME in names
            assert DB_ARCHIVE_NAME in names
            assert SETTINGS_ARCHIVE_NAME in names
            assert CONFIG_ARCHIVE_NAME in names
            assert "data/google_token.json" in names

            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))

        assert manifest["format_version"] == ARCHIVE_FORMAT_VERSION
        assert DB_ARCHIVE_NAME in manifest["included_files"]

    def test_import_migration_archive_restores_db_and_settings(self, tmp_path):
        from timereaper.database import get_activities, insert_activity
        from timereaper.migration import create_migration_archive, import_migration_archive
        from timereaper.user_settings import get_user_settings, save_user_settings

        # まず「復元したい状態」を作ってエクスポート
        insert_activity(
            timestamp="2026-03-02T09:00:00",
            app_name="OriginalApp",
            window_title="original",
            duration_seconds=120.0,
            is_idle=False,
            project="A",
            work_phase="設計",
            category="development",
        )
        save_user_settings({"pomodoro": {"enabled": True, "work_minutes": 45}})
        archive = create_migration_archive(
            output_path=str(tmp_path / "before.zip"),
            include_config=False,
        )

        # 現在状態を変更（インポートで上書きされる想定）
        insert_activity(
            timestamp="2026-03-02T10:00:00",
            app_name="NewApp",
            window_title="new",
            duration_seconds=60.0,
            is_idle=False,
            project="B",
            work_phase="実装",
            category="development",
        )
        save_user_settings({"pomodoro": {"enabled": False, "work_minutes": 10}})

        result = import_migration_archive(
            archive_path=archive,
            restore_config=False,
            create_backup=True,
        )

        activities = get_activities(limit=100)
        app_names = {a["app_name"] for a in activities}
        assert "OriginalApp" in app_names
        assert "NewApp" not in app_names

        settings = get_user_settings()
        assert settings["pomodoro"]["enabled"] is True
        assert settings["pomodoro"]["work_minutes"] == 45

        assert result["backup_path"] is not None
        assert Path(result["backup_path"]).exists()
        assert result["restored_count"] >= 2
