"""
設定管理モジュール
config.yaml を読み込み、アプリ全体で利用する設定を提供します。
"""

import os
import yaml
from pathlib import Path
from typing import Any

def _find_config_path() -> str:
    """config.yaml のパスを決定する（開発環境・py2app バンドル両対応）"""
    # 1. プロジェクトルート（開発環境）
    project_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
    )
    if os.path.exists(project_root):
        return project_root

    # 2. py2app バンドル内の Resources/
    if hasattr(os, "environ") and "__PYVENV_LAUNCHER__" not in os.environ:
        # バンドル: __file__ は .app/Contents/Resources/lib/python3.12/timetracker/config.py
        bundle_resources = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            os.pardir, os.pardir, os.pardir, "config.yaml"
        )
        bundle_resources = os.path.normpath(bundle_resources)
        if os.path.exists(bundle_resources):
            return bundle_resources

    # 3. ユーザーデータディレクトリ
    user_config = os.path.expanduser("~/.timetracker/config.yaml")
    if os.path.exists(user_config):
        return user_config

    # 4. フォールバック（開発環境パス）
    return project_root


_DEFAULT_CONFIG_PATH = _find_config_path()

_config: dict[str, Any] | None = None


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """設定ファイルを読み込んでキャッシュする"""
    global _config
    path = config_path or _DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    # パスの展開
    if "database" in _config and "path" in _config["database"]:
        _config["database"]["path"] = os.path.expanduser(_config["database"]["path"])
    if "google_calendar" in _config:
        gc = _config["google_calendar"]
        for key in ("credentials_path", "token_path"):
            if key in gc:
                gc[key] = os.path.expanduser(gc[key])
    return _config


def get_config() -> dict[str, Any]:
    """現在の設定を取得する（未読み込みなら読み込む）"""
    if _config is None:
        load_config()
    return _config


def ensure_data_dir():
    """データディレクトリを作成する"""
    cfg = get_config()
    db_path = cfg["database"]["path"]
    data_dir = os.path.dirname(db_path)
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    return data_dir


def add_tag_to_config(category: str, value: str) -> bool:
    """config.yaml の classification_rules にタグを追加し、ファイルに書き戻す

    Args:
        category: "task_categories" または "cost_categories"
        value: 追加するタグ値

    Returns:
        追加成功なら True、既に存在していたら False
    """
    global _config
    cfg = get_config()
    rules = cfg.setdefault("classification_rules", {})
    tags = rules.setdefault(category, [])

    if value in tags:
        return False

    tags.append(value)

    # YAML ファイルに書き戻す
    config_path = _DEFAULT_CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    raw.setdefault("classification_rules", {})[category] = tags

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return True
