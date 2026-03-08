"""
保守候補タスクの検知と、ユーザー判定フローの状態管理。

RC 版では「通知して summary 画面で判定」の導線を提供するため、
判定状態はメモリ上で管理する（アプリ再起動時はリセット）。
"""

from __future__ import annotations

import re
import time
import uuid
import threading
from collections import deque
from datetime import datetime

from .monitor import WindowInfo


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MaintenancePromptDetector:
    """保守候補のスコアリングと、未判定プロンプトの管理を行う。"""

    _COMM_APPS = {
        "Slack", "Mail", "Gmail", "Outlook", "Microsoft Teams", "Discord",
        "Jira", "Linear", "Confluence", "Notion",
    }
    _DEV_APPS = {
        "Visual Studio Code", "Code", "Cursor", "Terminal", "iTerm", "iTerm2",
        "Warp", "Xcode", "IntelliJ IDEA", "PyCharm", "WebStorm",
    }
    _TRANSITION_PHASES = {"meeting", "email", "planning", "documentation", "research"}
    _MAINT_KEYWORDS = re.compile(
        r"(障害|問い合わせ|不具合|緊急|保守|support|incident|hotfix|bugfix|oncall|alert|アラート)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        enabled: bool = False,
        threshold_score: int = 3,
        cooldown_minutes: int = 20,
        lookback_minutes: int = 15,
        snooze_minutes: int = 10,
    ):
        self._enabled = enabled
        self._threshold_score = threshold_score
        self._cooldown_seconds = cooldown_minutes * 60
        self._lookback_minutes = lookback_minutes
        self._snooze_seconds = snooze_minutes * 60

        self._lock = threading.Lock()
        self._recent_events: deque[dict] = deque(maxlen=40)
        self._last_prompt_at: float = 0
        self._snoozed_until: float = 0
        self._last_fingerprint: str = ""
        self._current_prompt: dict | None = None

    def update_config(
        self,
        *,
        enabled: bool | None = None,
        threshold_score: int | None = None,
        cooldown_minutes: int | None = None,
        lookback_minutes: int | None = None,
        snooze_minutes: int | None = None,
    ) -> None:
        with self._lock:
            if enabled is not None:
                self._enabled = enabled
            if threshold_score is not None:
                self._threshold_score = max(1, int(threshold_score))
            if cooldown_minutes is not None:
                self._cooldown_seconds = max(60, int(cooldown_minutes) * 60)
            if lookback_minutes is not None:
                self._lookback_minutes = max(1, int(lookback_minutes))
            if snooze_minutes is not None:
                self._snooze_seconds = max(60, int(snooze_minutes) * 60)

    def on_activity(self, window_info: WindowInfo, classification: dict) -> dict | None:
        """監視ループから呼ばれ、必要なら新しい判定プロンプトを生成する。"""
        now = time.time()
        app = window_info.app_name or ""
        phase = classification.get("work_phase") or ""
        project = classification.get("project") or ""
        text = " ".join(
            filter(
                None,
                [
                    app,
                    window_info.window_title,
                    window_info.tab_title,
                    window_info.url,
                    phase,
                    project,
                ],
            )
        )

        with self._lock:
            self._recent_events.append(
                {"ts": now, "app": app, "phase": phase}
            )

            if not self._enabled:
                return None

            if self._current_prompt is not None:
                return None

            if now < self._snoozed_until:
                return None

            if (now - self._last_prompt_at) < self._cooldown_seconds:
                return None

            score, reasons = self._score(text, app, phase, project, now)
            if score < self._threshold_score:
                return None

            fingerprint = f"{app}|{phase}|{window_info.url[:80]}|{window_info.window_title[:80]}"
            if fingerprint == self._last_fingerprint and (now - self._last_prompt_at) < (self._cooldown_seconds * 2):
                return None

            prompt = {
                "id": str(uuid.uuid4()),
                "status": "pending",
                "detected_at": _now_iso(),
                "score": score,
                "reasons": reasons,
                "lookback_minutes": self._lookback_minutes,
                "suggested_project": "Impulse保守開発・保守作業",
                "snapshot": {
                    "app_name": app,
                    "window_title": window_info.window_title or "",
                    "tab_title": window_info.tab_title or "",
                    "url": window_info.url or "",
                    "work_phase": phase,
                    "project": project,
                },
            }
            self._current_prompt = prompt
            self._last_prompt_at = now
            self._last_fingerprint = fingerprint
            return prompt.copy()

    def get_current_prompt(self) -> dict | None:
        with self._lock:
            if self._current_prompt is None:
                return None
            return self._current_prompt.copy()

    def decide(self, prompt_id: str, decision: str) -> dict:
        """ユーザー判定を受け取り、内部状態を更新する。"""
        now = time.time()
        with self._lock:
            if not self._current_prompt:
                return {"ok": False, "reason": "no_prompt"}

            if prompt_id and self._current_prompt.get("id") != prompt_id:
                return {"ok": False, "reason": "prompt_mismatch"}

            if decision not in {"maintenance", "development", "later"}:
                return {"ok": False, "reason": "invalid_decision"}

            current_id = self._current_prompt.get("id", "")
            if decision == "later":
                self._snoozed_until = now + self._snooze_seconds
            self._current_prompt = None
            return {"ok": True, "decision": decision, "prompt_id": current_id}

    def _score(
        self,
        text: str,
        app_name: str,
        work_phase: str,
        project: str,
        now: float,
    ) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        lower_text = text.lower()

        if app_name in self._COMM_APPS:
            score += 1
            reasons.append(f"連絡/管理系アプリ({app_name})")

        if self._MAINT_KEYWORDS.search(lower_text):
            score += 2
            reasons.append("障害/保守系キーワード")

        if not project:
            score += 1
            reasons.append("費用分類が未確定")

        if app_name in self._DEV_APPS and self._has_recent_transition(now):
            score += 1
            reasons.append("連絡→実装の遷移")

        if work_phase in {"meeting", "email", "planning"}:
            score += 1
            reasons.append(f"作業工程={work_phase}")

        return score, reasons

    def _has_recent_transition(self, now: float) -> bool:
        window_start = now - 10 * 60
        for e in reversed(self._recent_events):
            ts = e["ts"]
            if ts < window_start:
                break
            if e["phase"] in self._TRANSITION_PHASES or e["app"] in self._COMM_APPS:
                return True
        return False
