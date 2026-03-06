# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/ja/).

## [Unreleased]

### Added
- ローカル移行用のデータ export/import 機能を追加（クラウド不要）
  - CLI: `export-data` / `import-data`
  - Web: 設定画面に「📦 ローカルデータ移行」セクションを追加
  - インポート前に自動バックアップ（`~/.timereaper/backups/`）を作成
  - DB は SQLite backup API で整合性を保った復元を実施

## [0.8.1] - 2026-03-06

### Added
- 全ページ（ダッシュボード・日次サマリー・週次レポート）にアップデートチェック機能を追加
  - バージョンバッジクリックで手動チェック、ページ読み込み時に自動チェック
- メニューバーに「🔄 アップデートを確認」メニュー項目を追加
  - 更新あり・最新・エラーの3パターンで macOS 通知表示
- 設定ページに macOS 権限ステータスセクションを追加
  - アクセシビリティ・オートメーション・画面収録・通知の許可状態を検出・表示
  - 未許可時はシステム設定のパスを案内

### Fixed
- アップデーターの pip シンボリンク問題を修正（`python -m pip` に変更）

## [0.8.0] - 2026-03-06

### Added
- 日次・月次サマリーのエクスポート機能（Markdown / PDF）
  - PDF: 統計カード、横棒グラフ、割合カラーバー、時間帯別チャート、日別推移チャートを視覚的に出力
  - Markdown: Unicode ブロック文字による視覚バー付きテーブル
  - サマリーページ・週次ページに「📥 エクスポート」ドロップダウンを追加
- `get_monthly_report()` API: 月次集計データの取得
- pytest / mypy によるテスト・型チェック基盤
- ログレベルの config.yaml 設定対応

### Fixed
- PDF の日本語フォント表示不具合を修正（CID フォント HeiseiKakuGo-W5 に変更）

## [0.7.0] - 2026-03-04

### Changed
- 分類エンジン v2: 誤分類の大幅改善
  - デフォルト fallback 廃止: 推定根拠がない場合は project を空に（Finder/ChatGPT 等が「Impulse個別開発」になる問題を解消）
  - sub_phase の match_target 導入: 「実装」判定をアプリ名のみで行い、Chrome 記事閲覧時の誤検出を防止
  - standalone フェーズ（meeting/communication 等）でも project 推定を継続（早期 return 廃止）

### Added
- Slack チャンネル名からプロジェクト推定（slack_channel_rules）
- カレンダーイベントタイトルからプロジェクト推定（calendar_project_rules）
  - 会議タイトルに含まれるキーワードで費用分類を自動設定
- カレンダーイベントの3種分類（meeting / work / other）
  - meeting: 通常の会議 → work_phase="meeting" に上書き
  - work: 開発・作業ブロック → ウィンドウベースの分類を優先
  - other: 非作業イベント（お昼/不在/移動/私用等）→ project="その他"
- classify() に meeting_title パラメータ追加（menubar/CLI 両対応）

## [0.5.0] - 2026-03-03

### Changed
- アプリ名を TimeTracker → **TimeReaper** に変更
  - Python パッケージ: `timetracker/` → `timereaper/`
  - データディレクトリ: `~/.timetracker/` → `~/.timereaper/`（自動移行あり）
  - バンドルID: `com.timetracker.app` → `com.timereaper.app`
  - GitHub リポジトリ名: `TimeTracking` → `TimeReaper`
  - .app バンドル: `TimeTracker.app` → `TimeReaper.app`
  - DMG: `TimeTracker-v*.dmg` → `TimeReaper-v*.dmg`
  - DB ファイル: `timetracker.db` → `timereaper.db`（移行時自動リネーム）

## [0.4.0] - 2026-03-03

### Added
- ポモドーロタイマー統合 (pomodoro.py)
  - 作業/短休憩/長休憩のカウントダウンタイマー
  - セッションカウント、自動遷移、一時停止/再開/スキップ
  - Web UI から操作可能、リアルタイムステータス表示
  - タイマー完了時の macOS ネイティブ通知
- 長時間作業アラート (LongWorkAlert)
  - 連続作業時間が閾値を超えた場合に macOS 通知で休憩を促す
  - アイドル復帰時に自動リセット
  - 閾値・インターバル・メッセージのカスタマイズ
- 設定ページ (/settings)
  - ポモドーロ・長時間アラート・アイドル復帰サマリーの有効/無効切り替え
  - 各パラメータのカスタマイズ (Web UI)
  - ユーザー設定は ~/.timereaper/user_settings.json に保存
  - 設定変更がメニューバーアプリに即座に反映
- REST API: /api/settings, /api/pomodoro/status, /api/pomodoro/<action>
- 全ページに⚙設定リンク追加

### Fixed
- .app バンドルでのアップデートチェッカー修正
  - requests/urllib3/certifi を .app バンドルに同梱
  - pre-release も検出するよう GitHub API を /releases/latest → /releases に変更
  - .app 環境での DMG ダウンロード → 自動インストール → 再起動フローを実装
  - 開発環境では従来の git pull、.app では DMG 方式を自動切替

## [0.3.1] - 2026-03-03

### Fixed
- .app バンドルからの起動時（引数なし）にデフォルトで start コマンドを実行するよう修正
  - DMG からインストールしたアプリがダブルクリックで起動しない問題を解消

## [0.3.0] - 2026-03-03

### Added
- アップデート通知: GitHub Releases/Tags API によるバージョンチェック
- アップデート自動適用: git pull ベースの更新 + ダッシュボードバナー UI
- メニューバーアプリ: 更新通知表示
- 分類精度向上: URLAnalyzer を classify() に統合
  - Google Meet/Zoom → meeting, Slack → communication 等 URL サービス判定
  - GitHub URL からリポジトリ名を抽出しプロジェクト推定を強化
- LLM 分類: OpenAI API によるバッチ自動分類 (llm_classifier.py)
  - /api/llm-classify, /api/llm-status エンドポイント
  - サマリーページに AI 分類ボタン
- 週次レポートページ (/weekly)
  - 7日間日別サマリーグリッド
  - 日別スタック棒グラフ (Chart.js)
  - 作業工程ドーナツチャート + プロジェクト別横棒グラフ
  - 前週/翌週ナビゲーション
- サマリーページ: フィルタ機能 (作業工程・プロジェクト・アプリ)
- ページ間ナビゲーション改善 (全ページ相互リンク)

### Changed
- setup.sh: macOS/Python バージョンチェック、--update/--help オプション追加
- バージョンを 0.2.0 → 0.3.0 に更新

## [0.2.0] - 2026-03-03

### Added
- 日次サマリーページ: 10分ブロック単位のタグ一括編集 (#15)
- サマリーページ: Shift+クリックで範囲選択
- サマリーページ: 各ブロックにタブ/ウィンドウタイトルを補足表示
- ダッシュボード: タグ編集 UI (#14)
- ダッシュボード: カード→セクションスクロール
- 2軸分類システム: タスク分類 + コスト分類 (#11)
- Mac Calendar 連携: EventKit ヘルパーアプリ経由 (#8, #9)
- カレンダーイベント中の自動 meeting 分類 (#10)
- ブラウザタブタイトル記録 (#6, #12)
- 起動スクリプト + LaunchAgent による自動起動 (#13)
- py2app パッケージング (#7)
- ビルドスクリプト (scripts/build.sh)
- アイコン生成スクリプト (scripts/generate_icon.py)
- リリース手順書 (docs/RELEASE.md)
- バージョン管理一元化 (__init__.py → setup.py 自動読み込み)

### Fixed
- UTC タイムゾーンによる日付ずれ修正 (#15)
- Electron アプリ名の解決改善

## [0.1.0] - 2026-02-25

### Added
- アクティブウィンドウ監視 (AppleScript ベース)
- ブラウザ URL 取得 (Chrome / Safari / Arc / Edge / Firefox)
- アイドル検出 (HIDIdleTime、5分閾値)
- アクティビティ自動分類
- Flask Web ダッシュボード (ダークテーマ、Chart.js)
- macOS メニューバー常駐 (rumps)
- CSV エクスポート
- Electron アプリ名の解決 (bundle ID マッピング)
