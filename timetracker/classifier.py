"""
アクティビティ分類エンジン
ウィンドウ情報からプロジェクト・作業工程を自動推定します。
"""

import re
import logging
from typing import Optional
from urllib.parse import urlparse

from .config import get_config
from .monitor import WindowInfo

logger = logging.getLogger(__name__)


class ActivityClassifier:
    """アクティビティを自動分類するクラス"""

    def __init__(self):
        self.config = get_config()
        self._compile_rules()

    def _compile_rules(self):
        """設定ファイルのルールを正規表現にコンパイル"""
        rules = self.config.get("classification_rules", {})

        # プロジェクトルール
        self.project_rules = []
        for proj in rules.get("projects", []):
            patterns = [re.compile(kw, re.IGNORECASE) for kw in proj.get("keywords", [])]
            self.project_rules.append({
                "name": proj["name"],
                "patterns": patterns,
            })

        # 作業工程ルール
        self.phase_rules = {}
        for phase_name, phase_config in rules.get("work_phases", {}).items():
            patterns = [re.compile(kw, re.IGNORECASE) for kw in phase_config.get("keywords", [])]
            self.phase_rules[phase_name] = patterns

    def classify(self, window_info: WindowInfo) -> dict:
        """ウィンドウ情報からプロジェクトと作業工程を推定する"""
        result = {
            "project": "",
            "work_phase": "",
            "category": self._get_app_category(window_info.app_name),
        }

        # マッチ対象テキスト（アプリ名 + タイトル + URL を結合）
        search_text = " ".join(filter(None, [
            window_info.app_name,
            window_info.window_title,
            window_info.url,
        ]))

        # プロジェクト推定
        result["project"] = self._match_project(search_text)

        # 作業工程推定
        result["work_phase"] = self._match_work_phase(search_text, window_info.app_name)

        return result

    def _match_project(self, text: str) -> str:
        """テキストからプロジェクトを推定"""
        for rule in self.project_rules:
            for pattern in rule["patterns"]:
                if pattern.search(text):
                    return rule["name"]
        return ""

    def _match_work_phase(self, text: str, app_name: str) -> str:
        """テキストから作業工程を推定"""
        for phase_name, patterns in self.phase_rules.items():
            for pattern in patterns:
                if pattern.search(text):
                    return phase_name
        return ""

    def _get_app_category(self, app_name: str) -> str:
        """アプリ名からカテゴリを推定"""
        categories = {
            "development": [
                "Visual Studio Code", "Code", "IntelliJ IDEA", "PyCharm",
                "WebStorm", "Xcode", "Terminal", "iTerm2", "iTerm",
                "Warp", "Alacritty", "Hyper", "Cursor",
            ],
            "browser": [
                "Google Chrome", "Safari", "Firefox", "Arc",
                "Microsoft Edge", "Brave Browser", "Opera",
            ],
            "communication": [
                "Slack", "Microsoft Teams", "Zoom", "Discord",
                "FaceTime", "Messages", "LINE", "Telegram",
            ],
            "design": [
                "Figma", "Sketch", "Adobe Photoshop", "Adobe Illustrator",
                "Adobe XD", "Affinity Designer", "Canva",
            ],
            "documentation": [
                "Notion", "Microsoft Word", "Google Docs",
                "Pages", "Obsidian", "Bear", "Craft",
            ],
            "productivity": [
                "Finder", "Preview", "Calendar", "Reminders",
                "Notes", "Spotlight",
            ],
            "media": [
                "Spotify", "Music", "YouTube", "VLC",
                "QuickTime Player",
            ],
        }

        for category, apps in categories.items():
            if app_name in apps:
                return category
        return "other"


class URLAnalyzer:
    """URLからより詳細な情報を抽出するクラス"""

    # 既知のサービスとその分類
    SERVICE_PATTERNS = {
        "github": {
            "pattern": r"github\.com/([^/]+)/([^/]+)",
            "service": "GitHub",
        },
        "jira": {
            "pattern": r"atlassian\.net/.*browse/([A-Z]+-\d+)",
            "service": "Jira",
        },
        "confluence": {
            "pattern": r"atlassian\.net/wiki",
            "service": "Confluence",
        },
        "notion": {
            "pattern": r"notion\.so",
            "service": "Notion",
        },
        "figma": {
            "pattern": r"figma\.com/(?:file|design)/([^/]+)",
            "service": "Figma",
        },
        "linear": {
            "pattern": r"linear\.app",
            "service": "Linear",
        },
        "google_docs": {
            "pattern": r"docs\.google\.com/(document|spreadsheets|presentation)",
            "service": "Google Docs",
        },
        "google_meet": {
            "pattern": r"meet\.google\.com",
            "service": "Google Meet",
        },
        "slack": {
            "pattern": r"app\.slack\.com",
            "service": "Slack",
        },
    }

    @classmethod
    def analyze(cls, url: str) -> dict:
        """URLから詳細情報を抽出"""
        if not url:
            return {}

        result = {
            "domain": "",
            "service": "",
            "details": {},
        }

        try:
            parsed = urlparse(url)
            result["domain"] = parsed.netloc
        except Exception:
            pass

        for name, config in cls.SERVICE_PATTERNS.items():
            match = re.search(config["pattern"], url)
            if match:
                result["service"] = config["service"]
                result["details"] = {
                    "match_groups": match.groups(),
                }
                break

        return result
