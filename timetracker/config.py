"""
設定管理モジュール
config.yaml を読み込み、アプリ全体で利用する設定を提供します。
"""

import os
import yaml
from pathlib import Path
from typing import Any

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
)

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
