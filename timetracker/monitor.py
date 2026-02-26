"""
macOS アクティブウィンドウモニター
pyobjc を使って、現在フォーカスされているアプリケーション、ウィンドウタイトル、
およびブラウザのURL（AppleScript経由）を取得します。
"""

import subprocess
import json
import time
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

try:
    from AppKit import NSWorkspace
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
        kCGWindowListExcludeDesktopElements,
    )
    HAS_PYOBJC = True
except ImportError:
    HAS_PYOBJC = False
    logging.warning("pyobjc が見つかりません。フォールバックモードで動作します。")

logger = logging.getLogger(__name__)


@dataclass
class WindowInfo:
    """アクティブウィンドウの情報"""
    app_name: str
    window_title: str
    bundle_id: str
    url: str  # ブラウザの場合のURL
    timestamp: str
    is_idle: bool

    def to_dict(self) -> dict:
        return asdict(self)


class ActiveWindowMonitor:
    """macOSのアクティブウィンドウを監視するクラス"""

    # ブラウザアプリのバンドルID対応表
    BROWSER_BUNDLE_IDS = {
        "com.google.Chrome": "Google Chrome",
        "com.apple.Safari": "Safari",
        "org.mozilla.firefox": "Firefox",
        "company.thebrowser.Browser": "Arc",
        "com.microsoft.edgemac": "Microsoft Edge",
        "com.brave.Browser": "Brave Browser",
    }

    BROWSER_NAMES = set(BROWSER_BUNDLE_IDS.values())

    def __init__(self, idle_threshold: int = 300):
        self.idle_threshold = idle_threshold
        self._last_input_time = time.time()

    def get_active_window(self) -> Optional[WindowInfo]:
        """現在のアクティブウィンドウ情報を取得する"""
        try:
            if HAS_PYOBJC:
                return self._get_active_window_pyobjc()
            else:
                return self._get_active_window_fallback()
        except Exception as e:
            logger.error(f"アクティブウィンドウ取得エラー: {e}")
            return None

    def _get_active_window_pyobjc(self) -> Optional[WindowInfo]:
        """pyobjcを使ってアクティブウィンドウ情報を取得"""
        workspace = NSWorkspace.sharedWorkspace()
        active_app = workspace.frontmostApplication()

        if active_app is None:
            return None

        app_name = active_app.localizedName() or ""
        bundle_id = active_app.bundleIdentifier() or ""
        pid = active_app.processIdentifier()

        # ウィンドウタイトルを取得
        window_title = self._get_window_title(pid)

        # ブラウザの場合、URLを取得
        url = ""
        if app_name in self.BROWSER_NAMES or bundle_id in self.BROWSER_BUNDLE_IDS:
            url = self._get_browser_url(app_name) or ""

        # アイドル状態チェック
        is_idle = self._check_idle()

        return WindowInfo(
            app_name=app_name,
            window_title=window_title,
            bundle_id=bundle_id,
            url=url,
            timestamp=datetime.now().isoformat(),
            is_idle=is_idle,
        )

    def _get_window_title(self, pid: int) -> str:
        """指定PIDのウィンドウタイトルを取得"""
        if not HAS_PYOBJC:
            return ""
        try:
            options = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
            window_list = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
            for window in window_list:
                if window.get("kCGWindowOwnerPID") == pid:
                    title = window.get("kCGWindowName", "")
                    if title:
                        return str(title)
            return ""
        except Exception as e:
            logger.debug(f"ウィンドウタイトル取得エラー: {e}")
            return ""

    def _get_browser_url(self, app_name: str) -> Optional[str]:
        """ブラウザの現在のタブURLをAppleScript経由で取得"""
        scripts = {
            "Google Chrome": '''
                tell application "Google Chrome"
                    if (count of windows) > 0 then
                        return URL of active tab of front window
                    end if
                end tell
            ''',
            "Safari": '''
                tell application "Safari"
                    if (count of windows) > 0 then
                        return URL of current tab of front window
                    end if
                end tell
            ''',
            "Arc": '''
                tell application "Arc"
                    if (count of windows) > 0 then
                        return URL of active tab of front window
                    end if
                end tell
            ''',
            "Microsoft Edge": '''
                tell application "Microsoft Edge"
                    if (count of windows) > 0 then
                        return URL of active tab of front window
                    end if
                end tell
            ''',
            "Brave Browser": '''
                tell application "Brave Browser"
                    if (count of windows) > 0 then
                        return URL of active tab of front window
                    end if
                end tell
            ''',
            "Firefox": '''
                tell application "System Events"
                    tell process "Firefox"
                        -- Firefoxは直接AppleScript対応していないためタイトルから取得
                        return name of front window
                    end tell
                end tell
            ''',
        }

        script = scripts.get(app_name)
        if not script:
            return None

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.debug(f"ブラウザURL取得エラー ({app_name}): {e}")

        return None

    def _check_idle(self) -> bool:
        """ユーザーがアイドル状態かチェック（HIDアイドル時間を取得）"""
        try:
            result = subprocess.run(
                ["ioreg", "-c", "IOHIDSystem"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            output = result.stdout
            # HIDIdleTime はナノ秒単位
            for line in output.split("\n"):
                if "HIDIdleTime" in line:
                    parts = line.split("=")
                    if len(parts) >= 2:
                        idle_ns = int(parts[-1].strip())
                        idle_seconds = idle_ns / 1_000_000_000
                        return idle_seconds > self.idle_threshold
        except Exception as e:
            logger.debug(f"アイドルチェックエラー: {e}")
        return False

    def _get_active_window_fallback(self) -> Optional[WindowInfo]:
        """pyobjcが使えない場合のフォールバック（AppleScript使用）"""
        script = '''
            tell application "System Events"
                set frontApp to first application process whose frontmost is true
                set appName to name of frontApp
                set bundleId to bundle identifier of frontApp
                try
                    set winTitle to name of front window of frontApp
                on error
                    set winTitle to ""
                end try
                return appName & "|||" & bundleId & "|||" & winTitle
            end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split("|||")
                app_name = parts[0] if len(parts) > 0 else ""
                bundle_id = parts[1] if len(parts) > 1 else ""
                window_title = parts[2] if len(parts) > 2 else ""

                url = ""
                if app_name in self.BROWSER_NAMES:
                    url = self._get_browser_url(app_name) or ""

                return WindowInfo(
                    app_name=app_name,
                    window_title=window_title,
                    bundle_id=bundle_id,
                    url=url,
                    timestamp=datetime.now().isoformat(),
                    is_idle=self._check_idle(),
                )
        except Exception as e:
            logger.error(f"フォールバック取得エラー: {e}")
        return None


# Chromium系ブラウザからタブ一覧を取得するユーティリティ
def get_chrome_tabs() -> list[dict]:
    """Google Chromeの全タブ情報を取得"""
    script = '''
        set tabList to {}
        tell application "Google Chrome"
            repeat with w in windows
                repeat with t in tabs of w
                    set end of tabList to (URL of t) & "|||" & (title of t)
                end repeat
            end repeat
        end tell
        set AppleScript's text item delimiters to "\\n"
        return tabList as text
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            tabs = []
            for line in result.stdout.strip().split("\n"):
                if "|||" in line:
                    url, title = line.split("|||", 1)
                    tabs.append({"url": url.strip(), "title": title.strip()})
            return tabs
    except Exception as e:
        logger.debug(f"Chromeタブ取得エラー: {e}")
    return []
