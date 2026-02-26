"""
Slack 連携モジュール
Slack APIを使ってアクティブなチャンネルや会話相手を自動記録します。
"""

import logging
from datetime import datetime
from typing import Optional

from ..config import get_config
from ..database import get_connection

logger = logging.getLogger(__name__)


class SlackTracker:
    """Slack のアクティビティを追跡するクラス"""

    def __init__(self):
        self.config = get_config()
        self.slack_config = self.config.get("slack", {})
        self.token = self.slack_config.get("token", "")
        self.workspace_name = self.slack_config.get("workspace_name", "")
        self._client = None

    @property
    def is_enabled(self) -> bool:
        return self.slack_config.get("enabled", False) and bool(self.token)

    def connect(self) -> bool:
        """Slack APIクライアントを初期化する"""
        if not self.is_enabled:
            logger.info("Slack連携は無効です")
            return False

        try:
            from slack_sdk import WebClient
            from slack_sdk.errors import SlackApiError

            self._client = WebClient(token=self.token)

            # 接続テスト
            response = self._client.auth_test()
            user = response["user"]
            team = response["team"]
            logger.info(f"Slack接続成功: {user}@{team}")
            return True

        except ImportError:
            logger.error(
                "Slack連携にはslack-sdkが必要です:\n"
                "pip install slack-sdk"
            )
            return False
        except Exception as e:
            logger.error(f"Slack接続エラー: {e}")
            return False

    def get_recent_channels(self, limit: int = 10) -> list[dict]:
        """最近アクティブだったチャンネルを取得"""
        if not self._client:
            if not self.connect():
                return []

        try:
            # ユーザーの会話一覧を取得
            response = self._client.conversations_list(
                types="public_channel,private_channel,im,mpim",
                limit=limit,
                exclude_archived=True,
            )

            channels = []
            for channel in response.get("channels", []):
                channel_info = {
                    "channel_id": channel.get("id", ""),
                    "channel_name": channel.get("name", "DM"),
                    "is_im": channel.get("is_im", False),
                    "is_channel": channel.get("is_channel", False),
                }

                # DMの場合、相手のユーザー名を取得
                if channel.get("is_im"):
                    user_id = channel.get("user", "")
                    if user_id:
                        try:
                            user_info = self._client.users_info(user=user_id)
                            channel_info["conversation_with"] = (
                                user_info["user"].get("real_name", "")
                                or user_info["user"].get("name", "")
                            )
                        except Exception:
                            channel_info["conversation_with"] = user_id
                else:
                    channel_info["conversation_with"] = ""

                channels.append(channel_info)

            return channels

        except Exception as e:
            logger.error(f"Slackチャンネル取得エラー: {e}")
            return []

    def record_activity(self, channel_name: str, channel_id: str, conversation_with: str = ""):
        """Slackアクティビティを記録する"""
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO slack_activity
                (timestamp, channel_name, channel_id, workspace, is_active, conversation_with)
                VALUES (?, ?, ?, ?, 1, ?)""",
                (
                    datetime.now().isoformat(),
                    channel_name,
                    channel_id,
                    self.workspace_name,
                    conversation_with,
                ),
            )

    def get_active_channel_from_window(self, window_title: str) -> Optional[dict]:
        """ウィンドウタイトルからSlackのアクティブチャンネルを推定する"""
        if not window_title:
            return None

        # Slackのウィンドウタイトルは通常 "チャンネル名 - ワークスペース名 - Slack" の形式
        parts = window_title.split(" - ")
        if len(parts) >= 2:
            return {
                "channel_name": parts[0].strip(),
                "workspace": parts[1].strip() if len(parts) >= 3 else "",
            }

        return None
