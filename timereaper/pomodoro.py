"""
ポモドーロタイマー & 長時間作業アラート
メニューバーアプリと連携し、作業/休憩サイクルを管理する。
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class PomodoroState(Enum):
    """ポモドーロの状態"""
    IDLE = "idle"
    WORKING = "working"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"
    PAUSED = "paused"


@dataclass
class PomodoroStatus:
    """ポモドーロの現在のステータス"""
    state: PomodoroState = PomodoroState.IDLE
    remaining_seconds: int = 0
    total_seconds: int = 0
    session_count: int = 0
    is_running: bool = False

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "remaining_seconds": self.remaining_seconds,
            "total_seconds": self.total_seconds,
            "session_count": self.session_count,
            "is_running": self.is_running,
            "remaining_display": self._format_time(self.remaining_seconds),
        }

    @staticmethod
    def _format_time(seconds: int) -> str:
        m, s = divmod(max(0, seconds), 60)
        return f"{m:02d}:{s:02d}"


class PomodoroTimer:
    """ポモドーロタイマーのコアロジック"""

    def __init__(
        self,
        work_minutes: int = 25,
        short_break_minutes: int = 5,
        long_break_minutes: int = 15,
        sessions_before_long_break: int = 4,
        auto_start_break: bool = True,
        auto_start_work: bool = False,
        on_state_change: Optional[Callable[[PomodoroStatus], None]] = None,
        on_timer_complete: Optional[Callable[[PomodoroState], None]] = None,
    ):
        self.work_seconds = work_minutes * 60
        self.short_break_seconds = short_break_minutes * 60
        self.long_break_seconds = long_break_minutes * 60
        self.sessions_before_long_break = sessions_before_long_break
        self.auto_start_break = auto_start_break
        self.auto_start_work = auto_start_work
        self.on_state_change = on_state_change
        self.on_timer_complete = on_timer_complete

        self._state = PomodoroState.IDLE
        self._remaining = 0
        self._total = 0
        self._session_count = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def status(self) -> PomodoroStatus:
        with self._lock:
            return PomodoroStatus(
                state=self._state,
                remaining_seconds=self._remaining,
                total_seconds=self._total,
                session_count=self._session_count,
                is_running=self._running,
            )

    def start_work(self) -> PomodoroStatus:
        """作業セッションを開始"""
        with self._lock:
            self._state = PomodoroState.WORKING
            self._remaining = self.work_seconds
            self._total = self.work_seconds
            self._running = True
        self._start_ticker()
        self._notify_change()
        logger.info(f"ポモドーロ: 作業開始 ({self.work_seconds // 60}分)")
        return self.status

    def start_break(self) -> PomodoroStatus:
        """休憩を開始"""
        with self._lock:
            is_long = (self._session_count % self.sessions_before_long_break == 0
                       and self._session_count > 0)
            if is_long:
                self._state = PomodoroState.LONG_BREAK
                self._remaining = self.long_break_seconds
                self._total = self.long_break_seconds
            else:
                self._state = PomodoroState.SHORT_BREAK
                self._remaining = self.short_break_seconds
                self._total = self.short_break_seconds
            self._running = True
        self._start_ticker()
        self._notify_change()
        break_type = "長休憩" if self._state == PomodoroState.LONG_BREAK else "短休憩"
        logger.info(f"ポモドーロ: {break_type}開始 ({self._total // 60}分)")
        return self.status

    def pause(self) -> PomodoroStatus:
        """一時停止"""
        with self._lock:
            if self._running:
                self._running = False
                self._state = PomodoroState.PAUSED
        self._notify_change()
        return self.status

    def resume(self) -> PomodoroStatus:
        """再開"""
        with self._lock:
            if self._state == PomodoroState.PAUSED and self._remaining > 0:
                # 前の状態に基づいて復帰（remaining から判断）
                if self._total == self.work_seconds:
                    self._state = PomodoroState.WORKING
                elif self._total == self.long_break_seconds:
                    self._state = PomodoroState.LONG_BREAK
                else:
                    self._state = PomodoroState.SHORT_BREAK
                self._running = True
        self._start_ticker()
        self._notify_change()
        return self.status

    def stop(self) -> PomodoroStatus:
        """完全に停止してリセット"""
        with self._lock:
            self._running = False
            self._state = PomodoroState.IDLE
            self._remaining = 0
            self._total = 0
            self._session_count = 0
        self._notify_change()
        logger.info("ポモドーロ: 停止")
        return self.status

    def skip(self) -> PomodoroStatus:
        """現在のセッションをスキップ"""
        with self._lock:
            was_working = self._state == PomodoroState.WORKING
            self._running = False
            if was_working:
                self._session_count += 1
        if was_working and self.auto_start_break:
            return self.start_break()
        elif not was_working and self.auto_start_work:
            return self.start_work()
        else:
            with self._lock:
                self._state = PomodoroState.IDLE
                self._remaining = 0
            self._notify_change()
            return self.status

    def update_config(self, **kwargs):
        """設定を動的に更新する"""
        if "work_minutes" in kwargs:
            self.work_seconds = kwargs["work_minutes"] * 60
        if "short_break_minutes" in kwargs:
            self.short_break_seconds = kwargs["short_break_minutes"] * 60
        if "long_break_minutes" in kwargs:
            self.long_break_seconds = kwargs["long_break_minutes"] * 60
        if "sessions_before_long_break" in kwargs:
            self.sessions_before_long_break = kwargs["sessions_before_long_break"]
        if "auto_start_break" in kwargs:
            self.auto_start_break = kwargs["auto_start_break"]
        if "auto_start_work" in kwargs:
            self.auto_start_work = kwargs["auto_start_work"]

    def _start_ticker(self):
        """タイマースレッドを開始"""
        if self._thread and self._thread.is_alive():
            return  # 既存スレッドが動いていれば何もしない
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()

    def _tick_loop(self):
        """毎秒カウントダウンするループ"""
        while True:
            completed_state = None
            with self._lock:
                if not self._running:
                    return
                self._remaining -= 1
                if self._remaining <= 0:
                    self._remaining = 0
                    self._running = False
                    completed_state = self._state
                    # 作業完了→セッション数を増やす
                    if completed_state == PomodoroState.WORKING:
                        self._session_count += 1
                    self._state = PomodoroState.IDLE

            if completed_state is not None:
                # タイマー完了コールバック
                if self.on_timer_complete:
                    try:
                        self.on_timer_complete(completed_state)
                    except Exception as e:
                        logger.error(f"タイマー完了コールバックエラー: {e}")

                # 自動遷移
                if completed_state == PomodoroState.WORKING and self.auto_start_break:
                    self.start_break()
                elif completed_state in (PomodoroState.SHORT_BREAK, PomodoroState.LONG_BREAK) and self.auto_start_work:
                    self.start_work()
                return

            time.sleep(1)

    def _notify_change(self):
        """状態変更コールバックを呼ぶ"""
        if self.on_state_change:
            try:
                self.on_state_change(self.status)
            except Exception as e:
                logger.error(f"状態変更コールバックエラー: {e}")


class LongWorkAlert:
    """長時間連続作業のアラート管理"""

    def __init__(
        self,
        threshold_minutes: int = 60,
        interval_minutes: int = 30,
        message: str = "長時間の連続作業です。休憩を取りましょう！",
        on_alert: Optional[Callable[[str, int], None]] = None,
    ):
        self.threshold_seconds = threshold_minutes * 60
        self.interval_seconds = interval_minutes * 60
        self.message = message
        self.on_alert = on_alert

        self._continuous_work_start: float = 0
        self._last_alert_time: float = 0
        self._enabled = True
        self._lock = threading.Lock()

    def update_config(self, **kwargs):
        """設定を動的に更新する"""
        if "threshold_minutes" in kwargs:
            self.threshold_seconds = kwargs["threshold_minutes"] * 60
        if "interval_minutes" in kwargs:
            self.interval_seconds = kwargs["interval_minutes"] * 60
        if "message" in kwargs:
            self.message = kwargs["message"]

    def on_activity(self, is_idle: bool):
        """アクティビティ更新ごとに呼ばれる"""
        if not self._enabled:
            return

        now = time.time()
        with self._lock:
            if is_idle:
                # アイドル状態 → 連続作業タイマーをリセット
                self._continuous_work_start = 0
                self._last_alert_time = 0
                return

            # 作業中
            if self._continuous_work_start == 0:
                self._continuous_work_start = now

            elapsed = now - self._continuous_work_start
            if elapsed >= self.threshold_seconds:
                # 閾値超過 → アラート（interval ごと）
                if (now - self._last_alert_time) >= self.interval_seconds:
                    self._last_alert_time = now
                    elapsed_minutes = int(elapsed // 60)
                    if self.on_alert:
                        try:
                            self.on_alert(self.message, elapsed_minutes)
                        except Exception as e:
                            logger.error(f"長時間作業アラートエラー: {e}")

    def reset(self):
        """手動リセット（休憩ボタン押下時など）"""
        with self._lock:
            self._continuous_work_start = 0
            self._last_alert_time = 0
