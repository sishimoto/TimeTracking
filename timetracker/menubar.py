"""
macOS メニューバーアプリ
rumps を使ってメニューバーに常駐し、モニタリングの開始/停止やダッシュボードへの
アクセスを提供します。
"""

import threading
import webbrowser
import logging
import time
from datetime import datetime

import rumps

from .config import get_config
from .database import init_db, insert_activity, get_daily_summary, get_current_meeting
from .monitor import ActiveWindowMonitor, WindowInfo
from .classifier import ActivityClassifier
from .dashboard import run_dashboard

logger = logging.getLogger(__name__)


class TimeTrackerApp(rumps.App):
    """メニューバーに常駐するTimeTrackerアプリ"""

    def __init__(self):
        super().__init__(
            "TimeTracker",
            icon=None,
            title="⏱",
            quit_button=None,
        )
        self.config = get_config()
        self.monitor = ActiveWindowMonitor(
            idle_threshold=self.config.get("monitor", {}).get("idle_threshold_seconds", 300)
        )
        self.classifier = ActivityClassifier()
        self.is_tracking = False
        self._tracker_thread = None
        self._dashboard_thread = None
        self._last_window: WindowInfo | None = None
        self._last_timestamp: float = 0
        self._is_currently_idle: bool = False

        # メニュー構築
        self.menu = [
            rumps.MenuItem("▶ 記録開始", callback=self.toggle_tracking),
            None,  # separator
            rumps.MenuItem("📊 ダッシュボードを開く", callback=self.open_dashboard),
            None,
            rumps.MenuItem("今日の作業時間", callback=None),
            None,
            rumps.MenuItem("終了", callback=self.quit_app),
        ]

        # カレンダー同期
        self._last_calendar_sync: float = 0

        # DB初期化
        init_db()

        # ダッシュボードサーバー起動
        self._start_dashboard()

        # 自動で記録開始
        self._start_tracking()

        # カレンダー初回同期（バックグラウンド）
        self._schedule_calendar_sync()

    def toggle_tracking(self, sender):
        """記録の開始/停止を切り替え"""
        if self.is_tracking:
            self._stop_tracking()
            sender.title = "▶ 記録開始"
        else:
            self._start_tracking()
            sender.title = "⏸ 記録停止"

    def _start_tracking(self):
        """バックグラウンドでトラッキングを開始"""
        if self.is_tracking:
            return
        self.is_tracking = True
        self._tracker_thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self._tracker_thread.start()
        self.title = "⏱ REC"
        # メニュー項目を更新
        if "▶ 記録開始" in [item.title for item in self.menu.values() if hasattr(item, 'title')]:
            for item in self.menu.values():
                if hasattr(item, 'title') and item.title == "▶ 記録開始":
                    item.title = "⏸ 記録停止"
        logger.info("トラッキング開始")

    def _stop_tracking(self):
        """トラッキングを停止"""
        self.is_tracking = False
        self.title = "⏱"
        logger.info("トラッキング停止")

    def _tracking_loop(self):
        """メインのトラッキングループ"""
        interval = self.config.get("monitor", {}).get("interval_seconds", 5)

        while self.is_tracking:
            try:
                window_info = self.monitor.get_active_window()
                if window_info:
                    now = time.time()

                    if window_info.is_idle:
                        # アイドル状態 → 記録をスキップ（計測一時停止）
                        if not self._is_currently_idle:
                            # アイドル開始の遷移を記録
                            logger.info("アイドル検出 - 計測を一時停止")
                            self._is_currently_idle = True
                        self.title = "⏱ 💤"
                    else:
                        # アクティブ状態
                        if self._is_currently_idle:
                            # アイドルから復帰 → タイムスタンプをリセット
                            logger.info("アイドル復帰 - 計測を再開")
                            self._is_currently_idle = False
                            self._last_timestamp = now  # アイドル期間を含めないようリセット

                        # 前回からの経過時間を計算
                        duration = 0
                        if self._last_timestamp > 0:
                            duration = min(now - self._last_timestamp, interval * 2)

                        # アクティビティを分類
                        classification = self.classifier.classify(window_info)

                        # カレンダーに会議があれば work_phase を meeting に上書き
                        current_meeting = get_current_meeting()
                        if current_meeting:
                            classification["work_phase"] = "meeting"

                        # データベースに保存（アクティブ時のみ）
                        insert_activity(
                            app_name=window_info.app_name,
                            window_title=window_info.window_title,
                            bundle_id=window_info.bundle_id,
                            url=window_info.url,
                            tab_title=window_info.tab_title,
                            duration_seconds=duration,
                            is_idle=False,
                            project=classification["project"],
                            work_phase=classification["work_phase"],
                            category=classification["category"],
                            timestamp=window_info.timestamp,
                        )

                        self._last_timestamp = now
                        self.title = "⏱ REC"

                    self._last_window = window_info

            except Exception as e:
                logger.error(f"トラッキングエラー: {e}")

            time.sleep(interval)

    def _start_dashboard(self):
        """ダッシュボードサーバーをバックグラウンドで起動"""
        self._dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
        self._dashboard_thread.start()
        logger.info("ダッシュボードサーバー起動")

    def open_dashboard(self, _):
        """ブラウザでダッシュボードを開く"""
        cfg = self.config.get("dashboard", {})
        host = cfg.get("host", "127.0.0.1")
        port = cfg.get("port", 5555)
        webbrowser.open(f"http://{host}:{port}")

    def _schedule_calendar_sync(self):
        """カレンダー同期をバックグラウンドで実行する"""
        mac_cal_config = self.config.get("mac_calendar", {})
        if not mac_cal_config.get("enabled", False):
            return

        thread = threading.Thread(target=self._sync_calendar, daemon=True)
        thread.start()

    def _sync_calendar(self):
        """カレンダー同期の実処理"""
        try:
            from .integrations.mac_calendar import MacCalendarSync
            sync = MacCalendarSync()
            events = sync.sync_events(days_ahead=1)
            self._last_calendar_sync = time.time()
            logger.info(f"カレンダー同期完了: {len(events)} 件")
        except Exception as e:
            logger.error(f"カレンダー同期エラー: {e}")

    @rumps.timer(60)
    def update_status(self, _):
        """1分ごとにステータスメニューを更新 + カレンダー定期同期チェック"""
        try:
            summary = get_daily_summary()
            total_seconds = sum(r.get("total_seconds", 0) for r in summary)
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            status_text = f"今日: {hours}h {minutes}m"

            for item in self.menu.values():
                if hasattr(item, 'title') and item.title.startswith("今日"):
                    item.title = status_text
                    break
        except Exception as e:
            logger.debug(f"ステータス更新エラー: {e}")

        # カレンダー定期同期（sync_interval_seconds ごと）
        cal_interval = self.config.get("mac_calendar", {}).get("sync_interval_seconds", 3600)
        if time.time() - self._last_calendar_sync >= cal_interval:
            self._schedule_calendar_sync()

    def quit_app(self, _):
        """アプリを終了"""
        self.is_tracking = False
        rumps.quit_application()


def run_menubar_app():
    """メニューバーアプリを起動する"""
    app = TimeTrackerApp()
    app.run()
