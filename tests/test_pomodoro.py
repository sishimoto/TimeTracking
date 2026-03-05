"""
pomodoro.py のユニットテスト
"""

import time
import threading

import pytest

from timereaper.pomodoro import PomodoroTimer, PomodoroState, PomodoroStatus, LongWorkAlert


class TestPomodoroStatus:
    """PomodoroStatus のテスト"""

    def test_default_status(self):
        """デフォルトステータス"""
        status = PomodoroStatus()
        assert status.state == PomodoroState.IDLE
        assert status.remaining_seconds == 0
        assert status.is_running is False

    def test_to_dict(self):
        """to_dict の出力形式"""
        status = PomodoroStatus(
            state=PomodoroState.WORKING,
            remaining_seconds=1500,
            total_seconds=1500,
            session_count=1,
            is_running=True,
        )
        d = status.to_dict()
        assert d["state"] == "working"
        assert d["remaining_seconds"] == 1500
        assert d["is_running"] is True
        assert d["remaining_display"] == "25:00"

    def test_format_time(self):
        """時間表示フォーマット"""
        assert PomodoroStatus._format_time(0) == "00:00"
        assert PomodoroStatus._format_time(61) == "01:01"
        assert PomodoroStatus._format_time(3600) == "60:00"
        assert PomodoroStatus._format_time(-1) == "00:00"


class TestPomodoroTimer:
    """PomodoroTimer のテスト（タイマースレッドは使わず状態遷移をテスト）"""

    def test_initial_state(self):
        """初期状態は IDLE"""
        timer = PomodoroTimer(auto_start_break=False, auto_start_work=False)
        status = timer.status
        assert status.state == PomodoroState.IDLE
        assert status.is_running is False
        assert status.session_count == 0

    def test_start_work(self):
        """作業開始で WORKING に遷移"""
        timer = PomodoroTimer(
            work_minutes=25,
            auto_start_break=False,
            auto_start_work=False,
        )
        status = timer.start_work()
        assert status.state == PomodoroState.WORKING
        assert status.is_running is True
        assert status.total_seconds == 25 * 60
        # タイマースレッドが先に1秒消費する可能性がある
        assert status.remaining_seconds >= 25 * 60 - 2
        timer.stop()

    def test_start_break_short(self):
        """短休憩の開始"""
        timer = PomodoroTimer(
            short_break_minutes=5,
            auto_start_break=False,
            auto_start_work=False,
        )
        status = timer.start_break()
        assert status.state == PomodoroState.SHORT_BREAK
        assert status.total_seconds == 5 * 60
        assert status.remaining_seconds >= 5 * 60 - 2
        timer.stop()

    def test_start_break_long(self):
        """4セッション後の長休憩"""
        timer = PomodoroTimer(
            long_break_minutes=15,
            sessions_before_long_break=4,
            auto_start_break=False,
            auto_start_work=False,
        )
        # 4セッション完了した状態を模擬
        timer._session_count = 4
        status = timer.start_break()
        assert status.state == PomodoroState.LONG_BREAK
        assert status.total_seconds == 15 * 60
        assert status.remaining_seconds >= 15 * 60 - 2
        timer.stop()

    def test_pause_and_resume(self):
        """一時停止と再開"""
        timer = PomodoroTimer(auto_start_break=False, auto_start_work=False)
        timer.start_work()

        # 一時停止
        status = timer.pause()
        assert status.state == PomodoroState.PAUSED
        assert status.is_running is False

        # 再開
        status = timer.resume()
        assert status.state == PomodoroState.WORKING
        assert status.is_running is True
        timer.stop()

    def test_stop_resets(self):
        """停止で完全リセット"""
        timer = PomodoroTimer(auto_start_break=False, auto_start_work=False)
        timer.start_work()
        timer._session_count = 3

        status = timer.stop()
        assert status.state == PomodoroState.IDLE
        assert status.is_running is False
        assert status.session_count == 0
        assert status.remaining_seconds == 0

    def test_skip_work_increments_session(self):
        """作業スキップでセッション数が増える"""
        timer = PomodoroTimer(auto_start_break=False, auto_start_work=False)
        timer.start_work()
        status = timer.skip()
        assert status.session_count == 1
        timer.stop()

    def test_skip_break_no_increment(self):
        """休憩スキップではセッション数が増えない"""
        timer = PomodoroTimer(auto_start_break=False, auto_start_work=False)
        timer.start_break()
        initial_count = timer.status.session_count
        status = timer.skip()
        assert status.session_count == initial_count
        timer.stop()

    def test_update_config(self):
        """設定の動的更新"""
        timer = PomodoroTimer(work_minutes=25, auto_start_break=False)
        timer.update_config(work_minutes=50, short_break_minutes=10)
        assert timer.work_seconds == 50 * 60
        assert timer.short_break_seconds == 10 * 60

    def test_state_change_callback(self):
        """状態変更コールバックが呼ばれる"""
        changes = []
        timer = PomodoroTimer(
            auto_start_break=False,
            auto_start_work=False,
            on_state_change=lambda s: changes.append(s.state),
        )
        timer.start_work()
        timer.pause()
        timer.stop()

        assert PomodoroState.WORKING in changes
        assert PomodoroState.PAUSED in changes
        assert PomodoroState.IDLE in changes


class TestLongWorkAlert:
    """LongWorkAlert のテスト"""

    def test_no_alert_below_threshold(self):
        """閾値未満ではアラートなし"""
        alerts = []
        alert = LongWorkAlert(
            threshold_minutes=60,
            on_alert=lambda msg, mins: alerts.append(mins),
        )
        alert.on_activity(is_idle=False)
        assert len(alerts) == 0

    def test_reset(self):
        """手動リセット"""
        alert = LongWorkAlert(threshold_minutes=60)
        alert.on_activity(is_idle=False)
        alert.reset()
        assert alert._continuous_work_start == 0
        assert alert._last_alert_time == 0

    def test_idle_resets(self):
        """アイドル状態で連続作業タイマーがリセットされる"""
        alert = LongWorkAlert(threshold_minutes=60)
        alert.on_activity(is_idle=False)
        assert alert._continuous_work_start > 0
        alert.on_activity(is_idle=True)
        assert alert._continuous_work_start == 0

    def test_update_config(self):
        """設定の動的更新"""
        alert = LongWorkAlert(threshold_minutes=60, interval_minutes=30)
        alert.update_config(threshold_minutes=90, interval_minutes=15)
        assert alert.threshold_seconds == 90 * 60
        assert alert.interval_seconds == 15 * 60
