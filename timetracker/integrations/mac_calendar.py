"""
Mac Calendar (EventKit ヘルパー) 連携モジュール
CalHelper.app（Swift 製 EventKit ヘルパー）を subprocess で起動し、
JSON ファイル経由でカレンダーイベントを取得します。

アーキテクチャ:
  - EventKit は .app バンドルとして `open` コマンドで起動しないと
    Internet Account（Google Calendar 等）のソースにアクセスできない
  - CalHelper.app は EventKit で全カレンダーを高速にクエリし、
    ~/.timetracker/cal_helper_output.json に結果を書き出す
  - Python 側は CalHelper を起動 → JSON を読み取り → DB に保存
"""

import json
import logging
import subprocess
import time
import hashlib
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from ..config import get_config
from ..database import insert_calendar_event

logger = logging.getLogger(__name__)

# CalHelper.app の場所（プロジェクトルートからの相対パス）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CALHELPER_APP = _PROJECT_ROOT / "CalHelper.app"
CALHELPER_OUTPUT = Path.home() / ".timetracker" / "cal_helper_output.json"

# CalHelper の応答待ち最大時間（秒）
CALHELPER_TIMEOUT = 30

# スキップするシステムカレンダー
SKIP_CALENDARS = {"日本の祝日", "誕生日", "Siriからの提案", "日時設定ありリマインダー", "Birthdays"}


class MacCalendarSync:
    """CalHelper.app を使った Mac カレンダー同期クラス"""

    def __init__(self):
        self.config = get_config()
        self.cal_config = self.config.get("mac_calendar", {})

    @property
    def is_enabled(self) -> bool:
        return self.cal_config.get("enabled", False)

    def _run_calhelper(self, args: list[str], timeout: int = CALHELPER_TIMEOUT) -> Optional[dict | list]:
        """CalHelper.app を起動して JSON 結果を返す

        Args:
            args: CalHelper に渡す引数（例: ['--list-calendars']）
            timeout: 応答待ちタイムアウト（秒）

        Returns:
            パース済み JSON データ、またはエラー時 None
        """
        if not CALHELPER_APP.exists():
            logger.error(f"CalHelper.app が見つかりません: {CALHELPER_APP}")
            return None

        # 前回の出力ファイルを削除
        if CALHELPER_OUTPUT.exists():
            CALHELPER_OUTPUT.unlink()

        # CalHelper.app を open コマンドで起動（.app バンドルとして起動が必須）
        cmd = ["open", str(CALHELPER_APP), "--args"] + args
        logger.debug(f"CalHelper 起動: {' '.join(cmd)}")

        try:
            subprocess.run(cmd, timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("CalHelper 起動タイムアウト")
            return None
        except Exception as e:
            logger.error(f"CalHelper 起動エラー: {e}")
            return None

        # 出力ファイルが書き出されるのを待つ
        wait_start = time.time()
        while time.time() - wait_start < timeout:
            if CALHELPER_OUTPUT.exists():
                # ファイルが書き終わるのを少し待つ
                time.sleep(0.5)
                try:
                    data = json.loads(CALHELPER_OUTPUT.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "error" in data:
                        logger.error(f"CalHelper エラー: {data['error']}")
                        return None
                    return data
                except json.JSONDecodeError:
                    # まだ書き途中の可能性
                    time.sleep(0.5)
                    continue
            time.sleep(1.0)

        logger.warning(f"CalHelper 応答タイムアウト（{timeout}秒）")
        return None

    def list_calendars(self) -> list[str]:
        """利用可能なカレンダー名の一覧を返す"""
        data = self._run_calhelper(["--list-calendars"], timeout=15)
        if data is None:
            return []

        return [cal["title"] for cal in data if isinstance(cal, dict) and "title" in cal]

    def list_calendars_detailed(self) -> list[dict]:
        """カレンダーの詳細情報（ソース名含む）を返す"""
        data = self._run_calhelper(["--list-calendars"], timeout=15)
        if data is None or not isinstance(data, list):
            return []
        return data

    def sync_events(
        self,
        target_date: Optional[str] = None,
        days_ahead: int = 1,
    ) -> list[dict]:
        """Mac カレンダーからイベントを取得して DB に保存する

        Args:
            target_date: 取得開始日 (YYYY-MM-DD)。None なら今日。
            days_ahead: 何日先まで取得するか。

        Returns:
            取得したイベントのリスト
        """
        if target_date is None:
            start_date = date.today().isoformat()
        else:
            start_date = target_date

        end_dt = datetime.fromisoformat(start_date) + timedelta(days=days_ahead)
        end_date = end_dt.strftime("%Y-%m-%d")

        # CalHelper でイベント取得
        args = ["--events", "--start", start_date, "--end", end_date]
        data = self._run_calhelper(args, timeout=CALHELPER_TIMEOUT)

        if data is None:
            logger.warning("CalHelper からイベントを取得できませんでした")
            return []

        # 対象カレンダーでフィルタ
        target_calendars = self.cal_config.get("calendar_names", [])
        skip_cals = SKIP_CALENDARS.copy()

        all_events = []
        for event in data:
            if not isinstance(event, dict):
                continue

            cal_name = event.get("calendar", "")

            # スキップ対象カレンダー
            if cal_name in skip_cals:
                continue

            # 対象カレンダーが指定されていれば、それ以外をスキップ
            if target_calendars and cal_name not in target_calendars:
                continue

            # event_id がなければハッシュ生成
            event_id = event.get("event_id", "")
            if not event_id:
                event_id = hashlib.md5(
                    f"{cal_name}{event.get('title', '')}{event.get('start_time', '')}".encode()
                ).hexdigest()

            event_data = {
                "event_id": event_id,
                "title": event.get("title", ""),
                "description": event.get("description", ""),
                "start_time": event.get("start_time", ""),
                "end_time": event.get("end_time", ""),
                "attendees": "",
                "location": event.get("location", ""),
                "calendar_id": cal_name,
            }

            insert_calendar_event(event_data)
            all_events.append(event_data)

        logger.info(f"Mac Calendar から {len(all_events)} 件のイベントを取得・保存")
        return all_events

    def get_current_meeting(self) -> Optional[dict]:
        """現在進行中のミーティングを取得する（DB から）"""
        from ..database import get_connection

        now = datetime.now().isoformat()
        with get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM calendar_events
                WHERE start_time <= ? AND end_time >= ?
                ORDER BY start_time DESC LIMIT 1""",
                (now, now),
            ).fetchone()
            return dict(row) if row else None
