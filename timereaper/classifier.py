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

■ 自動判定ロジック (v2):
  1. 独立カテゴリ判定（meeting / communication / email 等）
     → work_phase を設定するが、project 推定は引き続き実行
  2. プロジェクトタイプ判定（ウィンドウタイトル / URL のリポジトリ名）
     - "impulse-pj-*" → カスタム開発
     - "impulse*" (pj 以外) → プロダクト開発
     - マッチしない場合 → project 空（デフォルト fallback なし）
  3. Slack チャンネル名からプロジェクト推定
  4. カレンダーイベントタイトルからプロジェクト推定（会議中優先）
  5. サブフェーズ判定（アプリ名ベース or 全テキスト）
  6. タスク分類 = プロジェクトタイプ + サブフェーズ (例: "カスタム開発-実装")
  7. 費用分類 = プロジェクトタイプから自動導出
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
    "meeting", "email", "research",
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
        # match_target を読み込む（"app_name" or "search_text"）
        self.sub_phase_rules: list[dict] = []
        for phase_name, phase_config in rules.get("sub_phases", {}).items():
            patterns = [re.compile(kw, re.IGNORECASE) for kw in phase_config.get("keywords", [])]
            match_target = phase_config.get("match_target", "search_text")
            self.sub_phase_rules.append({
                "name": phase_name,
                "patterns": patterns,
                "match_target": match_target,
            })

        # 独立カテゴリ判定ルール（communication / email 等）
        self.standalone_rules: dict[str, list[re.Pattern]] = {}
        for phase_name, phase_config in rules.get("standalone_phases", {}).items():
            patterns = [re.compile(kw, re.IGNORECASE) for kw in phase_config.get("keywords", [])]
            self.standalone_rules[phase_name] = patterns

        # Slack チャンネル → プロジェクトマッピング（案C）
        self.slack_channel_rules: list[dict] = []
        for rule in rules.get("slack_channel_rules", []):
            self.slack_channel_rules.append({
                "channels": [ch.lower() for ch in rule.get("channels", [])],
                "project": rule.get("project", ""),
                "work_phase": rule.get("work_phase", ""),
            })

        # カレンダーイベントタイトル → プロジェクトマッピング（案B）
        self.calendar_project_rules: list[dict] = []
        for rule in rules.get("calendar_project_rules", []):
            patterns = [re.compile(kw, re.IGNORECASE) for kw in rule.get("keywords", [])]
            self.calendar_project_rules.append({
                "patterns": patterns,
                "project": rule.get("project", ""),
                "work_phase": rule.get("work_phase", ""),
            })

        # カレンダーイベント分類パターン
        self._calendar_work_patterns: list[re.Pattern] = [
            re.compile(kw, re.IGNORECASE)
            for kw in rules.get("calendar_work_patterns", [])
        ]
        self._calendar_other_patterns: list[re.Pattern] = [
            re.compile(kw, re.IGNORECASE)
            for kw in rules.get("calendar_other_patterns", [])
        ]

        # デフォルトプロジェクトタイプ
        self.default_project_type = rules.get("default_project_type", "")

    def classify(self, window_info: WindowInfo, meeting_title: str = "") -> dict:
        """ウィンドウ情報からタスク分類（work_phase）と費用分類（project）を推定する

        Args:
            window_info: アクティブウィンドウの情報
            meeting_title: カレンダーの会議タイトル（進行中の場合）

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
            getattr(window_info, 'tab_title', None),
        ]))

        # 0. URL 解析で追加コンテキストを取得
        url_context = URLAnalyzer.analyze(window_info.url) if window_info.url else {}
        url_service = url_context.get("service", "")

        # URL サービスからの独立カテゴリ上書き
        url_service_overrides = {
            "Google Meet": "meeting",
            "Slack": "meeting",
            "Google Docs": "documentation",
            "Confluence": "documentation",
            "Notion": "documentation",
            "Jira": "planning",
            "Linear": "planning",
            "Figma": "設計",  # サブフェーズとして扱う
        }

        # 1. 独立カテゴリの判定（meeting / email 等）
        standalone = self._match_standalone(search_text)

        # communication → meeting に統合
        if standalone == "communication":
            standalone = "meeting"

        # URL サービスから独立カテゴリを強化
        if not standalone and url_service in url_service_overrides:
            override = url_service_overrides[url_service]
            if override in STANDALONE_PHASES:
                standalone = override

        if standalone:
            result["work_phase"] = standalone
            # ★ v2: 独立カテゴリでも project 推定を継続する（早期 return しない）

        # 2. カレンダーイベントタイトルからプロジェクト推定（案B: 最優先）
        if meeting_title:
            cal_project = self._match_calendar_project(meeting_title)
            if cal_project:
                result["project"] = cal_project
                logger.debug(f"カレンダーからプロジェクト推定: {cal_project} (title={meeting_title})")

        # 3. Slack チャンネル名からプロジェクト推定（案C）
        if not result["project"] and window_info.app_name == "Slack":
            channel = self._extract_slack_channel(window_info.window_title)
            if channel:
                slack_project = self._match_slack_channel(channel)
                if slack_project:
                    result["project"] = slack_project
                    logger.debug(f"Slackチャンネルからプロジェクト推定: {slack_project} (channel={channel})")

        # 4. プロジェクトタイプ判定（カスタム開発 / プロダクト開発）
        if not result["project"]:
            project_type, cost_category = self._detect_project_type(search_text)

            # GitHub URLからプロジェクトタイプを推定（より精度の高い判定）
            if url_service == "GitHub" and url_context.get("details", {}).get("match_groups"):
                groups = url_context["details"]["match_groups"]
                if len(groups) >= 2:
                    repo_name = groups[1]  # リポジトリ名
                    # リポジトリ名でプロジェクトタイプを再判定
                    repo_type, repo_cost = self._detect_project_type(repo_name)
                    if repo_cost:
                        project_type = repo_type
                        cost_category = repo_cost

            result["project"] = cost_category

            # 独立カテゴリでない場合のみ work_phase を設定
            if not standalone:
                # 5. サブフェーズ判定（実装 / 設計 / テスト 等）
                sub_phase = self._match_sub_phase(search_text, window_info.app_name)

                # URL サービスからサブフェーズを強化
                if not sub_phase and url_service in url_service_overrides:
                    override = url_service_overrides[url_service]
                    if override not in STANDALONE_PHASES:
                        sub_phase = override

                # 6. タスク分類 = サブフェーズのみ（プロジェクトタイプとの合成はしない）
                if sub_phase:
                    result["work_phase"] = sub_phase

        logger.debug(
            f"分類結果: work_phase={result['work_phase']}, "
            f"project={result['project']}, category={result['category']}"
            f"{f', url_service={url_service}' if url_service else ''}"
            f"{f', meeting={meeting_title}' if meeting_title else ''}"
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

        ★ v2: マッチしない場合はデフォルト fallback せず空を返す

        Returns:
            (project_type, cost_category)
        """
        for rule in self.project_type_rules:
            for pattern in rule["patterns"]:
                if pattern.search(text):
                    ptype = rule["type"]
                    cost = rule["cost_category"] or PROJECT_TYPE_COST_MAP.get(ptype, "")
                    return ptype, cost

        # ★ v2: デフォルト fallback なし（推定根拠がない場合は空）
        return "", ""

    def _match_sub_phase(self, text: str, app_name: str) -> str:
        """サブフェーズ（実装 / 設計 / テスト 等）を判定

        ★ v2: match_target 設定に応じてアプリ名のみ or 全テキストでマッチ
        """
        for rule in self.sub_phase_rules:
            # match_target に応じてマッチ対象を選択
            match_text = app_name if rule["match_target"] == "app_name" else text
            for pattern in rule["patterns"]:
                if pattern.search(match_text):
                    return str(rule["name"])
        return ""

    def _extract_slack_channel(self, window_title: str) -> str:
        """Slackのウィンドウタイトルからチャンネル名を抽出する

        タイトル形式:
        - "channel-name（チャンネル） - workspace - Slack"
        - "channel-name（チャンネル） - workspace - N 個の新しいアイテム - Slack"
        - "User Name（DM） - workspace - Slack"  → 空文字を返す（DMは推定不可）
        - "スレッド - workspace - Slack"  → 空文字を返す
        """
        if not window_title:
            return ""
        # チャンネル名を抽出: "xxx（チャンネル）" パターン
        match = re.match(r'^(.+?)（チャンネル）', window_title)
        if match:
            return match.group(1).strip()
        return ""

    def _match_slack_channel(self, channel: str) -> str:
        """Slackチャンネル名からプロジェクトを推定する"""
        channel_lower = channel.lower()
        for rule in self.slack_channel_rules:
            if channel_lower in rule["channels"]:
                return str(rule["project"])
        # チャンネル名でプロジェクトタイプ判定も試行
        _, cost = self._detect_project_type(channel)
        return cost

    def classify_calendar_event(self, title: str) -> str:
        """カレンダーイベントの種類を判定する

        Returns:
            "meeting" - 会議イベント（work_phase を meeting に上書き）
            "work"    - 作業ブロック（ウィンドウベースの分類を優先）
            "other"   - 非作業イベント（project="その他"）
        """
        if not title:
            return "meeting"
        for pattern in self._calendar_work_patterns:
            if pattern.search(title):
                logger.debug(f"カレンダー work イベント: {title!r}")
                return "work"
        for pattern in self._calendar_other_patterns:
            if pattern.search(title):
                logger.debug(f"カレンダー other イベント: {title!r}")
                return "other"
        return "meeting"

    def _match_calendar_project(self, meeting_title: str) -> str:
        """カレンダーイベントタイトルからプロジェクトを推定する

        優先順:
          1. プロジェクトタイプルール（impulse-pj-xxx 等 → 高精度）
          2. カレンダー専用ルール（全社、定例 等 → 汎用）
        """
        # まずプロジェクトタイプ判定（高精度: impulse-pj-, impulse 等）
        _, cost = self._detect_project_type(meeting_title)
        if cost:
            return cost

        # 次にカレンダー専用ルール
        for rule in self.calendar_project_rules:
            for pattern in rule["patterns"]:
                if pattern.search(meeting_title):
                    return str(rule["project"])
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
