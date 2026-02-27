# TimeTracker - macOS稼働時間管理アプリ

アクティブなウィンドウを自動監視し、どの時間にどのアプリでどの作業をしていたかを記録・可視化するmacOSアプリです。

## 機能

### コア機能
- **アクティブウィンドウ監視** - 数秒ごとにフォーカス中のアプリとウィンドウタイトルを記録
- **ブラウザURL取得** - Chrome / Safari / Arc / Edge / Firefox のアクティブタブURLを取得
- **ブラウザタブタイトル記録** - 約60秒間隔でアクティブタブのタイトルを記録（Chrome / Safari / Arc / Edge / Brave）
- **アイドル検出** - マウス/キーボード操作がなければ自動的にアイドル状態として記録
- **自動分類エンジン** - アプリ名・URL・ウィンドウタイトルからプロジェクト・作業工程を自動推定
- **Electronアプリ対応** - VS Code, Miro, Warp等のElectron系アプリを正しい名前で記録

### ダッシュボード
- 合計作業時間 / アプリ使用数 / メイン作業種別 のサマリー
- 時間帯別ヒートマップ
- アプリ使用時間ランキング
- 作業工程（設計・実装・レビュー等）の内訳チャート
- タイムライン表示
- プロジェクト別作業時間のスタックバーチャート
- 日付ナビゲーション / 30秒自動更新

### 統合機能（オプション）
- **Mac Calendar連携** - macOS カレンダー経由で Google Calendar 等の予定を自動取得・表示
- **Google Calendar連携** - API直接連携で打ち合わせの参加者・時間を自動取得
- **Slack連携** - アクティブチャンネル・会話相手を記録
- **CSVエクスポート** - データを外部ツールで分析可能

## 構成

```
timetracking/
├── main.py                      # CLIエントリーポイント
├── config.yaml                  # 設定ファイル
├── requirements.txt             # 依存パッケージ
├── setup.sh                     # セットアップスクリプト
├── .github/
│   └── copilot-instructions.md  # AIコーディングエージェント用指示
├── docs/
│   └── TODO.md                  # ロードマップ / 機能管理
├── CalHelper.swift              # Mac Calendar ヘルパー（Swift）
├── CalHelper.app/               # ビルド済みヘルパー（.app バンドル）
└── timetracker/
    ├── __init__.py
    ├── config.py                # 設定管理
    ├── monitor.py               # アクティブウィンドウ監視
    ├── classifier.py            # アクティビティ自動分類
    ├── database.py              # SQLiteデータ層
    ├── dashboard.py             # Flask Webダッシュボード
    ├── menubar.py               # macOSメニューバーアプリ
    ├── templates/
    │   └── dashboard.html       # ダッシュボードUI
    └── integrations/
        ├── __init__.py
        ├── google_calendar.py   # Google Calendar連携
        ├── mac_calendar.py      # Mac Calendar連携（CalHelper経由）
        └── slack_tracker.py     # Slack連携
```

## セットアップ

### 1. セットアップスクリプトを実行

```bash
cd /path/to/timetracking
chmod +x setup.sh
./setup.sh
```

### 2. macOSの権限設定

ウィンドウ情報の取得に以下の権限が必要です：

1. **システム設定 → プライバシーとセキュリティ → アクセシビリティ**
   - ターミナルアプリ（Terminal / iTerm2 等）を許可
2. **画面収録**（macOS 14+の場合）
   - 同様にターミナルアプリを許可

### 3. 起動

```bash
# 仮想環境を有効化
source venv/bin/activate

# メニューバーアプリとして起動（推奨）
python main.py start

# または CLIモードでモニタリング
python main.py monitor
```

## 使い方

### メニューバーモード（推奨）

```bash
python main.py start
```

- メニューバーに ⏱ アイコンが表示されます
- 自動的にウィンドウ監視とダッシュボードサーバーが起動します
- ダッシュボードはメニューから「📊 ダッシュボードを開く」で表示
- ダッシュボード URL: http://127.0.0.1:5555

### CLIモード

```bash
python main.py monitor
```

ターミナルにリアルタイムでアクティビティログが表示されます。テスト・デバッグ用。

### ダッシュボードのみ

```bash
python main.py dashboard
```

### データエクスポート

```bash
python main.py export --start 2026-02-01 --end 2026-02-28 --output feb_report.csv
```

## 設定

`config.yaml` を編集してカスタマイズできます：

### 監視設定
- `monitor.interval_seconds` - チェック間隔（デフォルト: 5秒）
- `monitor.idle_threshold_seconds` - アイドル閾値（デフォルト: 300秒 = 5分）

### プロジェクト自動分類ルール

```yaml
classification_rules:
  projects:
    - name: "プロジェクトA"
      keywords: ["project-a", "github.com/org/project-a"]
    - name: "プロジェクトB"
      keywords: ["project-b", "jira.*/PROJB"]
```

URLやウィンドウタイトルに指定キーワードが含まれる場合、そのプロジェクトとして自動分類されます。

### 作業工程のルール

デフォルトで以下の工程が定義済み：
- `design` - Figma, Sketch, Miro等
- `implementation` - VS Code, Terminal, IDE等
- `review` - GitHub PR等
- `documentation` - Notion, Google Docs等
- `communication` - Slack, Zoom等
- `planning` - Jira, Linear等
- `research` - StackOverflow, Qiita等
- `email` - メールアプリ

### Mac Calendar連携（推奨）

macOS のカレンダーアプリに Google Calendar 等を同期させることで、予定をダッシュボードに表示できます。

1. **macOS カレンダーに Google アカウントを追加**
   - システム設定 → インターネットアカウント → Google → カレンダーを有効化
2. **CalHelper.app をビルド**（`setup.sh` 実行時に自動ビルドされます）
   ```bash
   swiftc -framework Cocoa -framework EventKit CalHelper.swift -o CalHelper.app/Contents/MacOS/CalHelper
   ```
3. **初回実行時にカレンダーアクセスを許可**
   - CalHelper.app が「カレンダーへのアクセスを許可しますか？」と聞いてくるので許可
4. **`config.yaml` で設定**
   ```yaml
   mac_calendar:
     enabled: true
     sync_interval_seconds: 3600
     calendar_names:
       - "your-email@example.com"
   ```
5. メニューバーアプリ起動後、1時間ごとに自動同期されます

### Google Calendar連携

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. Calendar API を有効化
3. OAuth 2.0 の認証情報を作成
4. `credentials.json` を `~/.timetracker/` に配置
5. `config.yaml` で `google_calendar.enabled: true` に設定

```bash
python main.py sync-calendar
```

### Slack連携

1. [Slack API](https://api.slack.com/apps) でAppを作成
2. Bot Token Scopes: `channels:read`, `conversations:read`, `users:read`
3. Bot User OAuth Token を設定

```yaml
slack:
  enabled: true
  token: "xoxb-your-token-here"
```

## データ保存先

- データベース: `~/.timetracker/timetracker.db` (SQLite)
- 設定ファイル: プロジェクトルートの `config.yaml`

## 今後の拡張アイデア

詳細は [docs/TODO.md](docs/TODO.md) を参照してください。

- AI によるアクティビティの自動要約
- 週次/月次レポートの自動生成
- ポモドーロタイマー統合
- チーム共有機能
- より高精度なプロジェクト推定（機械学習ベース）
