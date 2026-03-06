"""
ユーザー設定管理モジュール
ポモドーロタイマーや通知などのユーザー個人設定を管理する。
設定は ~/.timereaper/user_settings.json に保存される。
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path.home() / ".timereaper" / "user_settings.json"

# デフォルト設定
_DEFAULTS: dict[str, Any] = {
    "pomodoro": {
        "enabled": False,
        "work_minutes": 25,
        "short_break_minutes": 5,
        "long_break_minutes": 15,
        "sessions_before_long_break": 4,
        "auto_start_break": True,
        "auto_start_work": False,
        "sound_enabled": True,
    },
    "notifications": {
        "long_work_alert": {
            "enabled": False,
            "threshold_minutes": 60,
            "interval_minutes": 30,
            "message": "長時間の連続作業です。休憩を取りましょう！",
        },
        "idle_return_summary": {
            "enabled": False,
        },
    },
}

_settings: dict[str, Any] | None = None


def _ensure_dir():
    """設定ファイルのディレクトリを作成"""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_user_settings_path() -> Path:
    """ユーザー設定ファイルのパスを返す"""
    return _SETTINGS_PATH


def load_user_settings() -> dict[str, Any]:
    """ユーザー設定を読み込む（ファイルがなければデフォルトを返す）"""
    global _settings
    if _SETTINGS_PATH.exists():
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # デフォルトとマージ（保存されていないキーはデフォルトで補完）
            _settings = _deep_merge(_DEFAULTS, saved)
        except Exception as e:
            logger.warning(f"ユーザー設定の読み込みに失敗: {e}")
            _settings = _DEFAULTS.copy()
    else:
        _settings = _deep_merge(_DEFAULTS, {})
    return _settings


def get_user_settings() -> dict[str, Any]:
    """現在のユーザー設定を取得"""
    if _settings is None:
        return load_user_settings()
    return _settings


def save_user_settings(settings: dict[str, Any]) -> None:
    """ユーザー設定を保存する"""
    global _settings
    _ensure_dir()
    # デフォルトとマージして完全な設定にする
    _settings = _deep_merge(_DEFAULTS, settings)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(_settings, f, ensure_ascii=False, indent=2)
    logger.info("ユーザー設定を保存しました")


def update_user_settings(partial: dict[str, Any]) -> dict[str, Any]:
    """部分的にユーザー設定を更新する"""
    current = get_user_settings()
    merged = _deep_merge(current, partial)
    save_user_settings(merged)
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """辞書の深いマージ（override の値で base を上書き）"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
