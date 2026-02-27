"""
アクティビティ分類エンジン
ウィンドウ情報から「タスク分類」と「費用分類」を自動推定します。

■ 2軸分類体系:
  1. タスク分類 (work_phase): エンジニアの作業内容分析
     - 分析
     - カスタム開発-要件定義 / 設計 / 実装 / テスト
     - プロダクト開発-要件定義 / 設計 / 実装 / テスト
     - 導入-基本設計 / 導入試験・検証 / 導入作業 / トレーニング・顧客説明
     - meeting / communication / email / research / documentation / planning

  2. 費用分類 (project): 会計上の費用/資産計上区分
     - Impulse個別開発 / Impulse製品開発（共通機能の改良・強化）/ etc.

■ 自動判定ロジック:
  1. プロジェクトタイプ判定（ウィンドウタイトル / URL のリポジトリ名）
     - "impulse-pj-*" → カスタム開発
     - "impulse*" (pj 以外) → プロダクト開発
     - その他 → カスタム開発（デフォルト）
  2. サブフェーズ判定（使用アプリ / URL パターン）
     - IDE / Terminal → 実装
     - Figma / Miro → 設計
     - etc.
  3. タスク分類 = プロジェクトタイプ + サブフェーズ (例: "カスタム開発-実装")
  4. 費用分類 = プロジェクトタイプから自動導出
"""

import re
import logging
from typing import Optional
from urllib.parse import urlparse

from .config import get_config
from .monitor import WindowInfo

logger = logging.getLogger(__name__)


# --- プロジェクトタイプ → 費用分類のデフォルトマッピング ---
PROJECT_TYPE_COST_MAP: dict[str, str] = {
    "カスタム開発": "Impulse個別開発",
    "プロダクト開発": "Impulse製品開発（共通機能の改良・強化）",
    "導入": "Impulse導入作業",
    "分析": "Impulseデータ分析・対応（PoC）",
}

# --- 開発系サブフェーズを持つプロジェクトタイプ ---
DEV_SUB_PHASES = ["要件定義", "設計", "実装", "テスト"]

# --- 独立カテゴリ（プロジェクトタイプと合成しない） ---
STANDALONE_PHASES = {
    "meeting", "communication", "email", "research",
    "documentation", "planning",
}


class ActivityClassifier:
    """アクティビティを自動分類するクラス（2軸分類対応）"""

    def __init__(self):
        self.config = get_config()
        self._compile_rules()

    def _compile_rules(self):
        """設定ファイルのルールを正規表現にコンパイル"""
        rules = self.config.get("classification_rules", {})

        # プロジェクトタイプ判定ルール（優先度順）
        self.project_type_rules: list[dict] = []
        for pt in rules.get("project_types", []):
            patterns = [re.compile(kw, re.IGNORECASE) for kw in pt.get("keywords", [])]
            self.project_type_rules.append({
                "type": pt["type"],
                "patterns": patterns,
                "cost_category": pt.get("cost_category", ""),
            })

        # サブフェーズ判定ルール（設計 / 実装 / テスト 等）
        self.sub_phase_rules: dict[str, list[re.Pattern]] = {}
        for phase_name, phase_config in rules.get("sub_phases", {}).items():
            patterns = [re.compile(kw, re.IGNORECASE) for kw in phase_config.get("keywords", [])]
            self.sub_phase_rules[phase_name] = patterns

        # 独立カテゴリ判定ルール（communication / email 等）
        self.standalone_rules: dict[str, list[re.Pattern]] = {}
        for phase_name, phase_config in rules.get("standalone_phases", {}).items():
            patterns = [re.compile(kw, re.IGNORECASE) for kw in phase_config.get("keywords", [])]
            self.standalone_rules[phase_name] = patterns

        # デフォルトプロジェクトタイプ
        self.default_project_type = rules.get("default_project_type", "カスタム開発")

    def classify(self, window_info: WindowInfo) -> dict:
        """ウィンドウ情報からタスク分類（work_phase）と費用分類（project）を推定する

        Returns:
            {
                "project": "Impulse個別開発",          # 費用分類
                "work_phase": "カスタム開発-実装",       # タスク分類
                "category": "development",              # アプリカテゴリ
            }
        """
        result = {
            "project": "",
            "work_phase": "",
            "category": self._get_app_category(window_info.app_name),
        }

        # マッチ対象テキスト
        search_text = " ".join(filter(None, [
            window_info.app_name,
            window_info.window_title,
            window_info.url,
        ]))

        # 1. 独立カテゴリの判定（meeting / communication / email 等）
        standalone = self._match_standalone(search_text)
        if standalone:
            result["work_phase"] = standalone
            # 独立カテゴリには費用分類を割り当てない
            return result

        # 2. プロジェクトタイプ判定（カスタム開発 / プロダクト開発）
        project_type, cost_category = self._detect_project_type(search_text)

        # 3. サブフェーズ判定（実装 / 設計 / テスト 等）
        sub_phase = self._match_sub_phase(search_text, window_info.app_name)

        # 4. タスク分類 = プロジェクトタイプ + サブフェーズ
        if sub_phase:
            result["work_phase"] = f"{project_type}-{sub_phase}"
        else:
            result["work_phase"] = project_type

        # 5. 費用分類
        result["project"] = cost_category

        logger.debug(
            f"分類結果: work_phase={result['work_phase']}, "
            f"project={result['project']}, category={result['category']}"
        )
        return result

    def _match_standalone(self, text: str) -> str:
        """独立カテゴリにマッチするか判定"""
        for phase_name, patterns in self.standalone_rules.items():
            for pattern in patterns:
                if pattern.search(text):
                    return phase_name
        return ""

    def _detect_project_type(self, text: str) -> tuple[str, str]:
        """プロジェクトタイプと費用分類を判定する

        Returns:
            (project_type, cost_category)
        """
        for rule in self.project_type_rules:
            for pattern in rule["patterns"]:
                if pattern.search(text):
                    ptype = rule["type"]
                    cost = rule["cost_category"] or PROJECT_TYPE_COST_MAP.get(ptype, "")
                    return ptype, cost

        # デフォルト
        default = self.default_project_type
        return default, PROJECT_TYPE_COST_MAP.get(default, "")

    def _match_sub_phase(self, text: str, app_name: str) -> str:
        """サブフェーズ（実装 / 設計 / テスト 等）を判定"""
        for phase_name, patterns in self.sub_phase_rules.items():
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
