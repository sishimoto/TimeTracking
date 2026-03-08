"""
maintenance_prompt.py のユニットテスト
"""

from unittest.mock import patch

from timereaper.monitor import WindowInfo
from timereaper.maintenance_prompt import MaintenancePromptDetector


def _make_window(
    app_name: str = "Slack",
    window_title: str = "",
    url: str = "",
    tab_title: str = "",
) -> WindowInfo:
    return WindowInfo(
        app_name=app_name,
        window_title=window_title,
        bundle_id="",
        url=url,
        timestamp="2026-03-09T10:00:00",
        is_idle=False,
        tab_title=tab_title,
    )


class TestMaintenancePromptDetector:
    def test_disabled_detector_returns_none(self):
        detector = MaintenancePromptDetector(enabled=False)
        win = _make_window(window_title="障害調査")
        classification = {"work_phase": "meeting", "project": ""}
        assert detector.on_activity(win, classification) is None

    def test_detect_prompt_with_maintenance_keywords(self):
        detector = MaintenancePromptDetector(
            enabled=True,
            threshold_score=3,
            cooldown_minutes=20,
            lookback_minutes=15,
            snooze_minutes=10,
        )
        win = _make_window(
            app_name="Slack",
            window_title="障害対応の相談",
            url="https://app.slack.com/client/T000/C111",
        )
        classification = {"work_phase": "meeting", "project": ""}
        prompt = detector.on_activity(win, classification)
        assert prompt is not None
        assert prompt["status"] == "pending"
        assert prompt["score"] >= 3
        assert prompt["suggested_project"] == "Impulse保守開発・保守作業"
        assert detector.get_current_prompt() is not None

    @patch("timereaper.maintenance_prompt.time.time")
    def test_later_decision_applies_snooze(self, mock_time):
        now = 1000.0
        mock_time.side_effect = lambda: now
        detector = MaintenancePromptDetector(
            enabled=True,
            threshold_score=2,
            cooldown_minutes=1,
            lookback_minutes=10,
            snooze_minutes=10,
        )
        win = _make_window(app_name="Mail", window_title="incident report")
        classification = {"work_phase": "email", "project": ""}

        first = detector.on_activity(win, classification)
        assert first is not None

        result = detector.decide(first["id"], "later")
        assert result["ok"] is True
        assert detector.get_current_prompt() is None

        now += 120  # 2分経過（cooldownは超えるが snooze には達しない）
        assert detector.on_activity(win, classification) is None

        now += 600  # snooze 解除
        second = detector.on_activity(win, classification)
        assert second is not None
