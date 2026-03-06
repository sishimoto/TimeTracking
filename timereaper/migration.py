"""
ローカル移行（エクスポート/インポート）モジュール
個人データをクラウドに載せずに、zip アーカイブで移行する。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import ensure_data_dir, get_config_path, load_config
from .database import get_db_path, init_db
from .user_settings import get_user_settings_path, load_user_settings

ARCHIVE_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DB_ARCHIVE_NAME = "data/timereaper.db"
SETTINGS_ARCHIVE_NAME = "settings/user_settings.json"
CONFIG_ARCHIVE_NAME = "config/config.yaml"

_SQLITE_TEMP_SUFFIXES = ("-wal", "-shm", "-journal")
_SKIP_TOP_LEVEL_DIRS = {"backups"}


def _timestamp_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _snapshot_sqlite_db(src_path: Path, dst_path: Path) -> None:
    # DB 未作成時でも移行ファイルを生成できるように初期化しておく
    init_db()
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(src_path), timeout=30) as src_conn:
        with sqlite3.connect(str(dst_path), timeout=30) as dst_conn:
            src_conn.backup(dst_conn)


def _collect_data_files(data_dir: Path, db_path: Path, output_path: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    db_resolved = _safe_resolve(db_path)
    output_resolved = _safe_resolve(output_path)

    for path in data_dir.rglob("*"):
        if not path.is_file():
            continue

        rel = path.relative_to(data_dir)
        if rel.parts and rel.parts[0] in _SKIP_TOP_LEVEL_DIRS:
            continue
        if path.name.endswith(_SQLITE_TEMP_SUFFIXES):
            continue

        resolved = _safe_resolve(path)
        if resolved == db_resolved:
            continue
        if resolved == output_resolved:
            continue

        files.append((path, f"data/{rel.as_posix()}"))

    files.sort(key=lambda item: item[1])
    return files


def _default_export_path() -> Path:
    filename = f"timereaper_migration_{_timestamp_for_filename()}.zip"
    return Path.cwd() / filename


def create_migration_archive(output_path: str | None = None, include_config: bool = True) -> str:
    """移行用アーカイブ(zip)を作成する"""
    data_dir = Path(ensure_data_dir())
    db_path = Path(get_db_path())
    config_path = Path(get_config_path())
    settings_path = get_user_settings_path()

    out_path = Path(output_path).expanduser() if output_path else _default_export_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="timereaper-export-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        snapshot_db = tmp_root / "timereaper.db"
        _snapshot_sqlite_db(db_path, snapshot_db)

        included_files: list[str] = [DB_ARCHIVE_NAME]
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot_db, DB_ARCHIVE_NAME)

            for src, arcname in _collect_data_files(data_dir, db_path, out_path):
                zf.write(src, arcname)
                included_files.append(arcname)

            if settings_path.exists():
                zf.write(settings_path, SETTINGS_ARCHIVE_NAME)
                included_files.append(SETTINGS_ARCHIVE_NAME)

            if include_config and config_path.exists():
                zf.write(config_path, CONFIG_ARCHIVE_NAME)
                included_files.append(CONFIG_ARCHIVE_NAME)

            # 重複排除（user_settings が data/ にもあるケース）
            unique_files = sorted(set(included_files))
            manifest = {
                "format_version": ARCHIVE_FORMAT_VERSION,
                "app_name": "TimeReaper",
                "app_version": __version__,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "data_dir": str(data_dir),
                "db_path": str(db_path),
                "included_files": unique_files,
            }
            zf.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )

    return str(out_path)


def _restore_database(src_db_path: Path, dst_db_path: Path) -> None:
    dst_db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(src_db_path), timeout=30) as src_conn:
        with sqlite3.connect(str(dst_db_path), timeout=30) as dst_conn:
            src_conn.backup(dst_conn)


def _extract_archive_safely(zf: zipfile.ZipFile, dst_root: Path) -> None:
    """Zip Slip を避けるため、展開先パスを検証してから展開する"""
    root_resolved = _safe_resolve(dst_root)
    root_prefix = str(root_resolved) + os.sep

    for info in zf.infolist():
        target = _safe_resolve(dst_root / info.filename)
        target_str = str(target)
        if target_str != str(root_resolved) and not target_str.startswith(root_prefix):
            raise ValueError(f"不正なパスを含む zip です: {info.filename}")

        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)


def import_migration_archive(
    archive_path: str,
    restore_config: bool = True,
    create_backup: bool = True,
) -> dict[str, Any]:
    """移行アーカイブ(zip)を現在環境へ復元する"""
    archive = Path(archive_path).expanduser()
    if not archive.exists():
        raise FileNotFoundError(f"移行ファイルが見つかりません: {archive}")

    data_dir = Path(ensure_data_dir())
    db_path = Path(get_db_path())
    config_path = Path(get_config_path())
    settings_path = get_user_settings_path()

    warnings: list[str] = []
    restored_files: list[str] = []
    backup_path: str | None = None
    manifest: dict[str, Any] = {}

    if create_backup:
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / f"timereaper_pre_import_{_timestamp_for_filename()}.zip"
        backup_path = create_migration_archive(
            output_path=str(backup_file),
            include_config=restore_config,
        )

    with tempfile.TemporaryDirectory(prefix="timereaper-import-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                names = set(zf.namelist())
                if MANIFEST_NAME not in names:
                    raise ValueError("移行ファイルが不正です: manifest.json がありません")
                if DB_ARCHIVE_NAME not in names:
                    raise ValueError("移行ファイルが不正です: data/timereaper.db がありません")

                manifest_raw = zf.read(MANIFEST_NAME).decode("utf-8")
                manifest = json.loads(manifest_raw)
                version = manifest.get("format_version")
                if version != ARCHIVE_FORMAT_VERSION:
                    warnings.append(
                        f"アーカイブ形式バージョンが想定外です: {version} (期待値: {ARCHIVE_FORMAT_VERSION})"
                    )

                _extract_archive_safely(zf, tmp_root)
        except zipfile.BadZipFile as e:
            raise ValueError(f"zip の読み込みに失敗しました: {e}") from e

        extracted_data_dir = tmp_root / "data"
        extracted_db = extracted_data_dir / "timereaper.db"
        _restore_database(extracted_db, db_path)
        restored_files.append(str(db_path))

        # data/ 配下のファイルを復元（db は上で別処理）
        if extracted_data_dir.exists():
            for src in extracted_data_dir.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(extracted_data_dir)
                if rel.as_posix() == "timereaper.db":
                    continue
                dst = data_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored_files.append(str(dst))

        # settings は data/ 外にも置けるよう専用エントリも復元
        extracted_settings = tmp_root / "settings" / "user_settings.json"
        if extracted_settings.exists():
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(extracted_settings, settings_path)
            if not _is_within(settings_path, data_dir):
                restored_files.append(str(settings_path))

        if restore_config:
            extracted_config = tmp_root / "config" / "config.yaml"
            if extracted_config.exists():
                try:
                    config_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(extracted_config, config_path)
                    restored_files.append(str(config_path))
                    load_config(str(config_path))
                except OSError as e:
                    warnings.append(f"config.yaml の復元に失敗しました: {e}")
            else:
                warnings.append("config.yaml はアーカイブに含まれていませんでした")

    # スキーマ補完とキャッシュ再読込
    init_db()
    load_user_settings()

    return {
        "backup_path": backup_path,
        "restored_files": sorted(set(restored_files)),
        "restored_count": len(set(restored_files)),
        "warnings": warnings,
        "manifest": manifest,
    }
