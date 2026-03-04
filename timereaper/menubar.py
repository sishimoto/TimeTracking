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

from . import __version__
from .config import get_config
from .database import init_db, insert_activity, get_daily_summary, get_current_meeting
from .monitor import ActiveWindowMonitor, WindowInfo
from .classifier import ActivityClassifier
from .dashboard import run_dashboard, set_pomodoro_timer, set_settings_change_callback
from .user_settings import load_user_settings, get_user_settings
from .pomodoro import PomodoroTimer, PomodoroState, LongWorkAlert

logger = logging.getLogger(__name__)


class TimeReaperApp(rumps.App):
    """メニューバーに常駐するTimeReaperアプリ"""

    def __init__(self):
        super().__init__(
            "TimeReaper",
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
        self._stop_event = threading.Event()  # スレッド停止用イベント
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
            rumps.MenuItem(f"v{__version__}", callback=None),
            rumps.MenuItem("終了", callback=self.quit_app),
        ]

        # カレンダー同期
        self._last_calendar_sync: float = 0

        # DB初期化
        init_db()

        # ユーザー設定を読み込み
        self._user_settings = load_user_settings()

        # ポモドーロタイマーの初期化
        self._pomodoro_timer = self._create_pomodoro_timer()
        set_pomodoro_timer(self._pomodoro_timer)

        # 長時間作業アラートの初期化
        self._long_work_alert = self._create_long_work_alert()

        # 設定変更コールバックの登録
        set_settings_change_callback(self._on_settings_changed)

        # ダッシュボードサーバー起動
        self._start_dashboard()

        # 自動で記録開始
        self._start_tracking()

        # カレンダー初回同期（バックグラウンド）
        self._schedule_calendar_sync()

        # アップデートチェック（バックグラウンド）
        self._check_for_updates()

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

        # 前のスレッドが残っていれば完全に停止してから再開
        if self._tracker_thread and self._tracker_thread.is_alive():
            logger.info("前のトラッキングスレッドの終了を待機中...")
            self._stop_event.set()
            self._tracker_thread.join(timeout=10)

        self._stop_event.clear()
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
        self._stop_event.set()  # スレッドに停止を通知
        if self._tracker_thread and self._tracker_thread.is_alive():
            self._tracker_thread.join(timeout=10)
        self.title = "⏱"
        logger.info("トラッキング停止")

    def _tracking_loop(self):
        """メインのトラッキングループ"""
        interval = self.config.get("monitor", {}).get("interval_seconds", 5)
        thread_id = threading.current_thread().ident
        logger.info(f"トラッキングループ開始 (thread={thread_id})")

        while self.is_tracking and not self._stop_event.is_set():
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
                        # 長時間アラート: アイドル通知
                        self._long_work_alert.on_activity(is_idle=True)
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

                        # カレンダーに会議があれば会議情報を取得
                        current_meeting = get_current_meeting()
                        meeting_title = current_meeting.get("title", "") if current_meeting else ""

                        # アクティビティを分類（会議タイトルも渡す）
                        classification = self.classifier.classify(window_info, meeting_title=meeting_title)

                        # 会議中かつ meeting イベントなら work_phase を meeting に上書き
                        if current_meeting and self.classifier.is_meeting_event(meeting_title):
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

                        # 長時間アラート: アクティブ通知
                        self._long_work_alert.on_activity(is_idle=False)

                    self._last_window = window_info

            except Exception as e:
                logger.error(f"トラッキングエラー: {e}")

            # time.sleep ではなく Event.wait で待機（停止要求に即応答）
            self._stop_event.wait(timeout=interval)

        logger.info(f"トラッキングループ終了 (thread={thread_id})")

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

    def _create_pomodoro_timer(self) -> PomodoroTimer:
        """ユーザー設定からポモドーロタイマーを生成する"""
        pom = self._user_settings.get("pomodoro", {})
        timer = PomodoroTimer(
            work_minutes=pom.get("work_minutes", 25),
            short_break_minutes=pom.get("short_break_minutes", 5),
            long_break_minutes=pom.get("long_break_minutes", 15),
            sessions_before_long_break=pom.get("sessions_before_long_break", 4),
            auto_start_break=pom.get("auto_start_break", True),
            auto_start_work=pom.get("auto_start_work", False),
            on_timer_complete=self._on_pomodoro_complete,
        )
        return timer

    def _create_long_work_alert(self) -> LongWorkAlert:
        """ユーザー設定から長時間作業アラートを生成する"""
        notif = self._user_settings.get("notifications", {})
        lwa = notif.get("long_work_alert", {})
        alert = LongWorkAlert(
            threshold_minutes=lwa.get("threshold_minutes", 60),
            interval_minutes=lwa.get("interval_minutes", 30),
            message=lwa.get("message", "長時間の連続作業です。休憩を取りましょう！"),
            on_alert=self._on_long_work_alert,
        )
        alert._enabled = lwa.get("enabled", False)
        return alert

    def _on_pomodoro_complete(self, completed_state: PomodoroState):
        """ポモドーロタイマー完了時のコールバック"""
        pom = self._user_settings.get("pomodoro", {})
        if not pom.get("enabled", False):
            return
        if completed_state == PomodoroState.WORKING:
            rumps.notification(
                title="🍅 ポモドーロ完了",
                subtitle="お疲れさまです！",
                message="休憩を取りましょう。",
            )
        elif completed_state in (PomodoroState.SHORT_BREAK, PomodoroState.LONG_BREAK):
            rumps.notification(
                title="☕ 休憩終了",
                subtitle="",
                message="作業を再開しましょう！",
            )

    def _on_long_work_alert(self, message: str, elapsed_minutes: int):
        """長時間作業アラートのコールバック"""
        rumps.notification(
            title="⏰ 長時間作業アラート",
            subtitle=f"連続 {elapsed_minutes} 分作業中",
            message=message,
        )

    def _on_settings_changed(self, new_settings: dict):
        """ダッシュボードから設定が変更されたときに呼ばれる"""
        self._user_settings = new_settings
        pom = new_settings.get("pomodoro", {})
        self._pomodoro_timer.update_config(
            work_minutes=pom.get("work_minutes", 25),
            short_break_minutes=pom.get("short_break_minutes", 5),
            long_break_minutes=pom.get("long_break_minutes", 15),
            sessions_before_long_break=pom.get("sessions_before_long_break", 4),
            auto_start_break=pom.get("auto_start_break", True),
            auto_start_work=pom.get("auto_start_work", False),
        )
        notif = new_settings.get("notifications", {})
        lwa = notif.get("long_work_alert", {})
        self._long_work_alert.update_config(
            threshold_minutes=lwa.get("threshold_minutes", 60),
            interval_minutes=lwa.get("interval_minutes", 30),
            message=lwa.get("message", "長時間の連続作業です。休憩を取りましょう！"),
        )
        self._long_work_alert._enabled = lwa.get("enabled", False)
        logger.info("ユーザー設定を反映しました")

    def _check_for_updates(self):
        """バックグラウンドでアップデートを確認し、通知を表示"""
        def _on_update(info):
            if info and info.is_update_available:
                logger.info(f"新バージョン v{info.latest_version} が利用可能です")
                rumps.notification(
                    title="TimeReaper アップデート",
                    subtitle=f"v{info.latest_version} が利用可能です",
                    message="ダッシュボードからアップデートできます。",
                )

        try:
            from .updater import check_for_updates_async
            check_for_updates_async(_on_update)
        except Exception as e:
            logger.warning(f"アップデートチェックをスキップ: {e}")


def run_menubar_app():
    """メニューバーアプリを起動する"""
    app = TimeReaperApp()
    app.run()
