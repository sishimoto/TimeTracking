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
    logging.info("pyobjc が見つかりません。AppleScriptモードで動作します。")

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
    tab_title: str = ""  # ブラウザのアクティブタブタイトル

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

    # バンドルIDから正しいアプリ名へのマッピング
    # Electron系アプリなど、プロセス名が "Electron" になるものを補正
    BUNDLE_ID_TO_APP_NAME = {
        # エディタ / IDE
        "com.microsoft.VSCode": "Visual Studio Code",
        "com.todesktop.runtime.Cursor": "Cursor",
        "com.vscodium": "VSCodium",
        # コミュニケーション
        "com.tinyspeck.slackmacgap": "Slack",
        "com.microsoft.teams2": "Microsoft Teams",
        "com.hnc.Discord": "Discord",
        # ドキュメント / プロジェクト管理
        "notion.id": "Notion",
        "com.figma.Desktop": "Figma",
        "com.linear": "Linear",
        "com.electron.realtimeboard": "Miro",
        # ターミナル
        "dev.warp.Warp-Stable": "Warp",
        "com.googlecode.iterm2": "iTerm2",
        # その他
        "com.spotify.client": "Spotify",
        "com.obsproject.obs-studio": "OBS Studio",
        "md.obsidian": "Obsidian",
        "com.1password.1password": "1Password",
        "com.openai.chat": "ChatGPT",
        # ブラウザ（BROWSER_BUNDLE_IDSと重複するがフォールバック用）
        **BROWSER_BUNDLE_IDS,
    }

    def __init__(self, idle_threshold: int = 300):
        self.idle_threshold = idle_threshold
        self._last_input_time = time.time()
        self._last_tab_title = ""
        self._last_tab_fetch_time: float = 0
        self._tab_fetch_interval = 60  # タブタイトル取得間隔（秒）

    def get_active_window(self) -> Optional[WindowInfo]:
        """現在のアクティブウィンドウ情報を取得する

        AppleScript (System Events) を使ってフォアグラウンドアプリを取得します。
        NSWorkspace.frontmostApplication() はバックグラウンドスレッドから呼ぶと
        キャッシュされた古い値を返すため、常にAppleScript経由で取得します。
        """
        try:
            return self._get_active_window_applescript()
        except Exception as e:
            logger.error(f"アクティブウィンドウ取得エラー: {e}")
            return None

    def _resolve_app_name(self, process_name: str, displayed_name: str, bundle_id: str) -> str:
        """プロセス名・表示名・バンドルIDからアプリの正しい名前を決定する

        優先順位:
        1. バンドルIDマッピング（最も信頼性が高い）
        2. displayed name（メニューバーに表示される名前）
        3. process name（フォールバック）
        """
        # 1. バンドルIDで既知アプリか確認
        if bundle_id in self.BUNDLE_ID_TO_APP_NAME:
            return self.BUNDLE_ID_TO_APP_NAME[bundle_id]

        # 2. displayed name が汎用名でなければそれを使う
        generic_names = {"Electron", "python", "Python", "node", "java", ""}
        if displayed_name and displayed_name not in generic_names:
            return displayed_name

        # 3. process name がEleectronでなければそれを使う
        if process_name and process_name not in generic_names:
            return process_name

        # 4. どれもダメならバンドルIDの末尾を使う
        if bundle_id:
            return bundle_id.split(".")[-1]
        return process_name or "Unknown"

    def _get_active_window_applescript(self) -> Optional[WindowInfo]:
        """AppleScript (System Events) で確実にフォアグラウンドアプリを取得"""
        script = '''
            tell application "System Events"
                set frontApp to first application process whose frontmost is true
                set procName to name of frontApp
                set dispName to displayed name of frontApp
                set bundleId to bundle identifier of frontApp
                try
                    set winTitle to name of front window of frontApp
                on error
                    set winTitle to ""
                end try
                return procName & "|||" & dispName & "|||" & bundleId & "|||" & winTitle
            end tell
        '''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
            if result.returncode != 0:
                logger.debug(f"AppleScript エラー: {result.stderr.strip()}")
                return None

            parts = result.stdout.strip().split("|||")
            process_name = parts[0].strip() if len(parts) > 0 else ""
            displayed_name = parts[1].strip() if len(parts) > 1 else ""
            bundle_id = parts[2].strip() if len(parts) > 2 else ""
            window_title = parts[3].strip() if len(parts) > 3 else ""

            # プロセス名・表示名・バンドルIDから正しいアプリ名を決定
            app_name = self._resolve_app_name(process_name, displayed_name, bundle_id)

            if not app_name:
                return None

            # ブラウザの場合、URLとタブタイトルを取得
            url = ""
            tab_title = ""
            is_browser = app_name in self.BROWSER_NAMES or bundle_id in self.BROWSER_BUNDLE_IDS
            if is_browser:
                url = self._get_browser_url(app_name) or ""
                tab_title = self._get_browser_tab_title_throttled(app_name)

            # アイドル状態チェック
            is_idle = self._check_idle()

            return WindowInfo(
                app_name=app_name,
                window_title=window_title,
                bundle_id=bundle_id,
                url=url,
                timestamp=datetime.now().isoformat(),
                is_idle=is_idle,
                tab_title=tab_title,
            )
        except subprocess.TimeoutExpired:
            logger.debug("AppleScript タイムアウト")
            return None
        except Exception as e:
            logger.error(f"アクティブウィンドウ取得エラー: {e}")
            return None

    def _get_browser_tab_title_throttled(self, app_name: str) -> str:
        """ブラウザのアクティブタブタイトルを取得（約60秒間隔でサンプリング）"""
        now = time.time()
        if now - self._last_tab_fetch_time < self._tab_fetch_interval:
            return self._last_tab_title

        tab_title = self._get_browser_tab_title(app_name)
        if tab_title:
            self._last_tab_title = tab_title
            self._last_tab_fetch_time = now
            logger.debug(f"タブタイトル取得: {tab_title[:60]}")
        return self._last_tab_title

    def _get_browser_tab_title(self, app_name: str) -> str:
        """AppleScript でブラウザのアクティブタブタイトルを取得"""
        scripts = {
            "Google Chrome": 'tell application "Google Chrome" to return title of active tab of front window',
            "Safari": 'tell application "Safari" to return name of current tab of front window',
            "Arc": 'tell application "Arc" to return title of active tab of front window',
            "Microsoft Edge": 'tell application "Microsoft Edge" to return title of active tab of front window',
            "Brave Browser": 'tell application "Brave Browser" to return title of active tab of front window',
        }
        script = scripts.get(app_name)
        if not script:
            return ""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.debug(f"タブタイトル取得エラー ({app_name}): {e}")
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
                encoding="utf-8",
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
                encoding="utf-8",
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
        """後方互換用のエイリアス"""
        return self._get_active_window_applescript()


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
            encoding="utf-8",
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
