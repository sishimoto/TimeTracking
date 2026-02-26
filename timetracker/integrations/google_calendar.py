"""
Google Calendar 連携モジュール
Google Calendar APIを使ってカレンダーイベントを取得し、
打ち合わせの参加者や時間を自動記録します。
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

from .config import get_config
from .database import insert_calendar_event, get_connection

logger = logging.getLogger(__name__)


class GoogleCalendarSync:
    """Google Calendar との同期クラス"""

    SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

    def __init__(self):
        self.config = get_config()
        self.gc_config = self.config.get("google_calendar", {})
        self.credentials_path = self.gc_config.get("credentials_path", "")
        self.token_path = self.gc_config.get("token_path", "")
        self.calendar_ids = self.gc_config.get("calendar_ids", ["primary"])
        self._service = None

    @property
    def is_enabled(self) -> bool:
        return self.gc_config.get("enabled", False)

    def authenticate(self):
        """Google Calendar APIの認証を行う"""
        if not self.is_enabled:
            logger.info("Google Calendar連携は無効です")
            return False

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            creds = None

            # 既存のトークンを読み込み
            if os.path.exists(self.token_path):
                creds = Credentials.from_authorized_user_file(
                    self.token_path, self.SCOPES
                )

            # トークンがない or 期限切れ → 再認証
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not os.path.exists(self.credentials_path):
                        logger.error(
                            f"認証ファイルが見つかりません: {self.credentials_path}\n"
                            "Google Cloud Consoleからcredentials.jsonをダウンロードしてください。"
                        )
                        return False

                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path, self.SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                # トークンを保存
                with open(self.token_path, "w") as token_file:
                    token_file.write(creds.to_json())

            self._service = build("calendar", "v3", credentials=creds)
            logger.info("Google Calendar認証成功")
            return True

        except ImportError:
            logger.error(
                "Google Calendar連携には追加パッケージが必要です:\n"
                "pip install google-api-python-client google-auth-httplib2 "
                "google-auth-oauthlib"
            )
            return False
        except Exception as e:
            logger.error(f"Google Calendar認証エラー: {e}")
            return False

    def sync_events(
        self,
        target_date: Optional[str] = None,
        days_ahead: int = 1,
    ) -> list[dict]:
        """カレンダーイベントを取得してDBに保存する"""
        if not self._service:
            if not self.authenticate():
                return []

        if target_date:
            start_dt = datetime.fromisoformat(target_date)
        else:
            start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        end_dt = start_dt + timedelta(days=days_ahead)

        time_min = start_dt.isoformat() + "Z"
        time_max = end_dt.isoformat() + "Z"

        all_events = []

        for calendar_id in self.calendar_ids:
            try:
                events_result = (
                    self._service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )

                events = events_result.get("items", [])

                for event in events:
                    start = event["start"].get("dateTime", event["start"].get("date", ""))
                    end = event["end"].get("dateTime", event["end"].get("date", ""))

                    # 参加者を抽出
                    attendees = []
                    for att in event.get("attendees", []):
                        name = att.get("displayName", att.get("email", ""))
                        if name:
                            attendees.append(name)

                    event_data = {
                        "event_id": event.get("id", ""),
                        "title": event.get("summary", ""),
                        "description": event.get("description", ""),
                        "start_time": start,
                        "end_time": end,
                        "attendees": ", ".join(attendees),
                        "location": event.get("location", ""),
                        "calendar_id": calendar_id,
                    }

                    insert_calendar_event(event_data)
                    all_events.append(event_data)

                logger.info(
                    f"カレンダー '{calendar_id}' から {len(events)} 件のイベントを取得"
                )

            except Exception as e:
                logger.error(f"カレンダー '{calendar_id}' の取得エラー: {e}")

        return all_events

    def get_current_meeting(self) -> Optional[dict]:
        """現在進行中のミーティングを取得する"""
        now = datetime.now().isoformat()

        with get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM calendar_events
                WHERE start_time <= ? AND end_time >= ?
                ORDER BY start_time DESC LIMIT 1""",
                (now, now),
            ).fetchone()

            return dict(row) if row else None
