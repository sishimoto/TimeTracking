# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/ja/).

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
  - ユーザー設定は ~/.timetracker/user_settings.json に保存
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
