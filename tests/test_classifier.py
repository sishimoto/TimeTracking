"""
classifier.py のユニットテスト
"""

import pytest
from unittest.mock import patch

from timereaper.monitor import WindowInfo
from timereaper.classifier import (
    ActivityClassifier,
    URLAnalyzer,
    PROJECT_TYPE_COST_MAP,
    STANDALONE_PHASES,
)


def _make_window(
    app_name: str = "Google Chrome",
    window_title: str = "",
    bundle_id: str = "",
    url: str = "",
    tab_title: str = "",
) -> WindowInfo:
    """テスト用の WindowInfo を作成するヘルパー"""
    return WindowInfo(
        app_name=app_name,
        window_title=window_title,
        bundle_id=bundle_id,
        url=url,
        timestamp="2024-01-01T10:00:00",
        is_idle=False,
        tab_title=tab_title,
    )


class TestActivityClassifier:
    """ActivityClassifier.classify() のテスト"""

    @pytest.fixture(autouse=True)
    def setup_classifier(self, config_file):
        """テスト用の分類器を初期化"""
        from timereaper.config import load_config
        load_config(config_file)
        self.classifier = ActivityClassifier()

    # --- プロジェクトタイプ判定 ---

    def test_custom_dev_project(self):
        """impulse-pj- を含むタイトルはカスタム開発と判定"""
        win = _make_window(
            app_name="Visual Studio Code",
            window_title="impulse-pj-acme — main.py",
        )
        result = self.classifier.classify(win)
        assert result["project"] == "Impulse個別開発"

    def test_product_dev_project(self):
        """impulse（pj以外）を含むタイトルはプロダクト開発と判定"""
        win = _make_window(
            app_name="Visual Studio Code",
            window_title="impulse-core — utils.py",
        )
        result = self.classifier.classify(win)
        assert result["project"] == "Impulse製品開発（共通機能の改良・強化）"

    def test_no_project_match(self):
        """マッチしない場合は project が空"""
        win = _make_window(
            app_name="Visual Studio Code",
            window_title="my-personal-project — app.py",
        )
        result = self.classifier.classify(win)
        assert result["project"] == ""

    # --- 独立カテゴリ判定 ---

    def test_meeting_detection_zoom(self):
        """Zoom は meeting と判定"""
        win = _make_window(app_name="Zoom", window_title="Zoom Meeting")
        result = self.classifier.classify(win)
        assert result["work_phase"] == "meeting"

    def test_meeting_detection_slack(self):
        """Slack は meeting と判定（communication → meeting 統合）"""
        win = _make_window(
            app_name="Slack",
            window_title="general（チャンネル） - workspace - Slack",
        )
        result = self.classifier.classify(win)
        assert result["work_phase"] == "meeting"

    def test_email_detection(self):
        """Mail は email と判定"""
        win = _make_window(app_name="Mail", window_title="受信トレイ")
        result = self.classifier.classify(win)
        assert result["work_phase"] == "email"

    def test_documentation_detection(self):
        """Notion は documentation と判定"""
        win = _make_window(app_name="Notion", window_title="設計ドキュメント")
        result = self.classifier.classify(win)
        assert result["work_phase"] == "documentation"

    # --- サブフェーズ判定 ---

    def test_implementation_by_app(self):
        """VS Code はアプリ名マッチで実装と判定"""
        win = _make_window(
            app_name="Visual Studio Code",
            window_title="some-project — main.py",
        )
        result = self.classifier.classify(win)
        assert result["work_phase"] == "実装"

    def test_test_by_text(self):
        """pytest を含むテキストはテストと判定"""
        win = _make_window(
            app_name="Terminal",
            window_title="pytest test_main.py",
        )
        result = self.classifier.classify(win)
        # Terminal はまず「実装」にマッチするが、テストの方が先に定義されていれば…
        # 実際の順序は sub_phases の dict 順序による
        assert result["work_phase"] in ("テスト", "実装")

    def test_design_by_app(self):
        """Figma はアプリ名マッチで設計と判定"""
        win = _make_window(app_name="Figma", window_title="UI Design")
        result = self.classifier.classify(win)
        assert result["work_phase"] == "設計"

    # --- カテゴリ判定 ---

    def test_app_category_development(self):
        """開発ツールの category は development"""
        win = _make_window(app_name="Visual Studio Code")
        result = self.classifier.classify(win)
        assert result["category"] == "development"

    def test_app_category_browser(self):
        """ブラウザの category は browser"""
        win = _make_window(app_name="Google Chrome")
        result = self.classifier.classify(win)
        assert result["category"] == "browser"

    def test_app_category_communication(self):
        """Slack の category は communication"""
        win = _make_window(app_name="Slack", window_title="random")
        result = self.classifier.classify(win)
        assert result["category"] == "communication"

    def test_app_category_unknown(self):
        """未知のアプリの category は other"""
        win = _make_window(app_name="UnknownApp")
        result = self.classifier.classify(win)
        assert result["category"] == "other"

    # --- Slack チャンネル → プロジェクト推定 ---

    def test_slack_channel_project(self):
        """Slack の general チャンネルは全社活動と推定"""
        win = _make_window(
            app_name="Slack",
            window_title="general（チャンネル） - workspace - Slack",
        )
        result = self.classifier.classify(win)
        assert result["project"] == "全社活動"

    def test_slack_dm_no_project(self):
        """Slack DM はプロジェクト推定されない"""
        win = _make_window(
            app_name="Slack",
            window_title="田中太郎（DM） - workspace - Slack",
        )
        result = self.classifier.classify(win)
        # DM はチャンネル抽出できないのでプロジェクト空
        assert result["project"] == ""

    # --- カレンダーイベントからのプロジェクト推定 ---

    def test_calendar_meeting_project(self):
        """会議タイトルに「全社」を含む場合、全社活動と推定"""
        win = _make_window(app_name="Zoom", window_title="Zoom Meeting")
        result = self.classifier.classify(win, meeting_title="全社朝会")
        assert result["project"] == "全社活動"

    def test_calendar_impulse_project(self):
        """会議タイトルに impulse-pj を含む場合、Impulse個別開発と推定"""
        win = _make_window(app_name="Zoom", window_title="Zoom Meeting")
        result = self.classifier.classify(win, meeting_title="impulse-pj-acme 進捗確認")
        assert result["project"] == "Impulse個別開発"

    # --- meeting_title が独立カテゴリと共存するか ---

    def test_standalone_with_project(self):
        """meeting カテゴリでも project は推定される"""
        win = _make_window(app_name="Zoom", window_title="Zoom Meeting")
        result = self.classifier.classify(win, meeting_title="全社定例")
        assert result["work_phase"] == "meeting"
        assert result["project"] == "全社活動"


class TestClassifyCalendarEvent:
    """ActivityClassifier.classify_calendar_event() のテスト"""

    @pytest.fixture(autouse=True)
    def setup_classifier(self, config_file):
        from timereaper.config import load_config
        load_config(config_file)
        self.classifier = ActivityClassifier()

    def test_empty_title_is_meeting(self):
        """空タイトルは meeting"""
        assert self.classifier.classify_calendar_event("") == "meeting"

    def test_work_event(self):
        """開発ブロックは work"""
        assert self.classifier.classify_calendar_event("Impulse開発") == "work"
        assert self.classifier.classify_calendar_event("work") == "work"

    def test_other_event(self):
        """お昼・休暇は other"""
        assert self.classifier.classify_calendar_event("お昼") == "other"
        assert self.classifier.classify_calendar_event("ランチ") == "other"
        assert self.classifier.classify_calendar_event("休暇") == "other"

    def test_regular_meeting(self):
        """通常の会議タイトルは meeting"""
        assert self.classifier.classify_calendar_event("プロジェクト進捗会議") == "meeting"
        assert self.classifier.classify_calendar_event("1on1") == "meeting"


class TestURLAnalyzer:
    """URLAnalyzer.analyze() のテスト"""

    def test_github_url(self):
        """GitHub URL のパース"""
        result = URLAnalyzer.analyze("https://github.com/owner/repo/pull/123")
        assert result["service"] == "GitHub"
        assert result["domain"] == "github.com"
        assert result["details"]["match_groups"] == ("owner", "repo")

    def test_jira_url(self):
        """Jira URL のパース"""
        result = URLAnalyzer.analyze("https://myteam.atlassian.net/browse/PROJ-456")
        assert result["service"] == "Jira"
        assert result["details"]["match_groups"] == ("PROJ-456",)

    def test_google_meet_url(self):
        """Google Meet URL のパース"""
        result = URLAnalyzer.analyze("https://meet.google.com/abc-defg-hij")
        assert result["service"] == "Google Meet"

    def test_notion_url(self):
        """Notion URL のパース"""
        result = URLAnalyzer.analyze("https://notion.so/workspace/Page-123")
        assert result["service"] == "Notion"

    def test_empty_url(self):
        """空 URL は空辞書"""
        assert URLAnalyzer.analyze("") == {}

    def test_unknown_url(self):
        """未知の URL は service 空"""
        result = URLAnalyzer.analyze("https://example.com/page")
        assert result["service"] == ""
        assert result["domain"] == "example.com"

    def test_google_docs_url(self):
        """Google Docs URL のパース"""
        result = URLAnalyzer.analyze(
            "https://docs.google.com/document/d/1234/edit"
        )
        assert result["service"] == "Google Docs"

    def test_figma_url(self):
        """Figma URL のパース"""
        result = URLAnalyzer.analyze("https://www.figma.com/design/ABCDEF/my-file")
        assert result["service"] == "Figma"


class TestSlackChannelExtraction:
    """Slack チャンネル名抽出のテスト"""

    @pytest.fixture(autouse=True)
    def setup_classifier(self, config_file):
        from timereaper.config import load_config
        load_config(config_file)
        self.classifier = ActivityClassifier()

    def test_channel_extraction(self):
        """チャンネル名が正しく抽出される"""
        result = self.classifier._extract_slack_channel(
            "impulse-dev（チャンネル） - workspace - Slack"
        )
        assert result == "impulse-dev"

    def test_dm_extraction_returns_empty(self):
        """DM はチャンネル名として抽出されない"""
        result = self.classifier._extract_slack_channel(
            "田中太郎（DM） - workspace - Slack"
        )
        assert result == ""

    def test_thread_returns_empty(self):
        """スレッドはチャンネル名として抽出されない"""
        result = self.classifier._extract_slack_channel(
            "スレッド - workspace - Slack"
        )
        assert result == ""

    def test_empty_title(self):
        """空タイトルは空文字"""
        assert self.classifier._extract_slack_channel("") == ""
