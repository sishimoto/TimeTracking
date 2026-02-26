# TimeTracker - AI Coding Agent Instructions

## Project Overview

macOS 稼働時間管理アプリ。アクティブウィンドウを自動監視し、どの時間にどのアプリでどの作業をしていたかを記録・可視化する。

**アーキテクチャ:** Python 単一パッケージ + Flask Web ダッシュボード + macOS メニューバー常駐

**Key Components:**
- `main.py`: CLI エントリーポイント（start / monitor / dashboard / sync-calendar / export）
- `timetracker/monitor.py`: AppleScript ベースのアクティブウィンドウ検出、アイドル検出
- `timetracker/classifier.py`: アプリ名・URL・タイトルからプロジェクト・作業工程を自動推定
- `timetracker/database.py`: SQLite データ層（activity_log, calendar_events, slack_activity, manual_tags, daily_summary）
- `timetracker/dashboard.py`: Flask Web ダッシュボード + REST API
- `timetracker/menubar.py`: rumps ベースの macOS メニューバーアプリ
- `timetracker/templates/dashboard.html`: Chart.js ダークテーマ UI
- `timetracker/integrations/`: Google Calendar / Slack 連携
- `config.yaml`: 全設定（監視間隔、分類ルール、連携設定）

**技術スタック:**
- Python 3.12, venv
- pyobjc（AppKit / Quartz インポートのみ、実際のウィンドウ検出は AppleScript）
- Flask 3.x + flask-cors
- Chart.js 4.x（CDN）
- rumps（メニューバー）
- SQLite（~/.timetracker/timetracker.db）
- google-api-python-client / slack-sdk（オプション連携）

## Development Environment Setup

```bash
# Python 3.12 で venv 作成
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### macOS 権限設定（必須）

ウィンドウ情報取得に以下の権限が必要：
1. **システム設定 → プライバシーとセキュリティ → アクセシビリティ** - ターミナルアプリを許可
2. **画面収録**（macOS 14+）- 同様にターミナルアプリを許可

### 起動方法

```bash
source venv/bin/activate

# メニューバーアプリ（推奨）
python main.py start

# CLI モニタリング（テスト・デバッグ用）
python main.py monitor

# ダッシュボードのみ
python main.py dashboard
```

ダッシュボード URL: http://127.0.0.1:5555

## Critical Architecture Decisions

### ウィンドウ検出: AppleScript 必須
- `NSWorkspace.frontmostApplication()` はバックグラウンドスレッドでキャッシュ値を返す（NSRunLoop 不在のため）
- **必ず AppleScript（osascript 経由 System Events）でウィンドウ情報を取得すること**
- 参照: `monitor.py` の `_get_active_window_applescript()`

### Electron アプリ名の解決
- Electron 系アプリ（VS Code, Miro, Warp 等）は `System Events` の `name` がプロセス名（"Electron", "stable" 等）になる
- `BUNDLE_ID_TO_APP_NAME` マッピング + `displayed name` で正しいアプリ名を解決
- 新しい Electron アプリ対応時は `monitor.py` の `BUNDLE_ID_TO_APP_NAME` にエントリ追加

### アイドル検出
- `ioreg -c IOHIDSystem` の `HIDIdleTime` を使用（ナノ秒）
- 閾値を超えると記録スキップ、復帰時にタイムスタンプをリセット

## Database Schema

SQLite at `~/.timetracker/timetracker.db`:
- `activity_log`: メインテーブル（timestamp, app_name, window_title, bundle_id, url, duration_seconds, is_idle, project, work_phase, category）
- `calendar_events`: Google Calendar イベント
- `slack_activity`: Slack アクティビティ
- `manual_tags`: 手動タグ付け
- `daily_summary`: 日次サマリーキャッシュ

## REST API Endpoints

- `GET /api/today` - 本日のサマリー
- `GET /api/daily/<date>` - 指定日のサマリー
- `GET /api/activities` - アクティビティ一覧
- `GET /api/projects` - プロジェクト別サマリー
- `GET /api/weekly` - 週次データ
- `GET /api/hourly/<date>` - 時間帯別データ

## Coding Conventions

### Python スタイル
- Python 3.12 の型ヒントを使用（`Optional`, `dict`, `list` 等）
- docstring は日本語で記述
- ログは `logging` モジュールを使用、`print` はユーザー向け CLI 出力のみ
- データクラスを適切に使用（例: `WindowInfo`）

### 設定管理
- 全設定は `config.yaml` に集約
- パス展開は `config.py` の `_expand_paths()` で行う（`~` → 絶対パス）
- ハードコードされたパスや値を避け、`get_config()` 経由でアクセス

### エラーハンドリング
- AppleScript 呼び出しは `subprocess.run` + try/except で保護
- DB 操作は `contextmanager` でコネクション管理
- 外部 API（Google Calendar, Slack）は `enabled` フラグで制御

## Testing

```bash
source venv/bin/activate

# 全モジュール動作テスト
python -c "
from timetracker.config import load_config, ensure_data_dir
from timetracker.database import init_db
load_config(); ensure_data_dir(); init_db()
from timetracker.monitor import ActiveWindowMonitor
m = ActiveWindowMonitor()
info = m.get_active_window()
print(f'App: {info.app_name}, Title: {info.window_title[:60]}')
"

# CLI モニタリングで実動作確認
python main.py monitor --verbose
```

## Key Patterns & Anti-Patterns

### ✅ Do
- AppleScript で全ウィンドウ情報を取得する（`name`, `displayed name`, `bundle identifier`, `front window name`）
- 新しいアプリ対応時は `BUNDLE_ID_TO_APP_NAME` と `BROWSER_BUNDLE_IDS` を確認
- `config.yaml` の分類ルール（keywords）でプロジェクト推定を拡張
- ダッシュボード変更時は `dashboard.html` のインライン JS/CSS を直接編集
- DB スキーマ変更時は `database.py` の `init_db()` で `CREATE TABLE IF NOT EXISTS` を使用

### ❌ Don't
- `NSWorkspace.frontmostApplication()` をバックグラウンドスレッドで使わない（キャッシュ問題）
- シークレット（credentials.json, token.json, Slack トークン）をコミットしない
- `~/.timetracker/` ディレクトリ内のファイルをリポジトリに含めない
- ダッシュボードを外部ネットワークに公開しない（`127.0.0.1` 固定）

## Git Repository

- Remote: https://github.com/sishimoto/TimeTracking
- Branch: main

### Commit Message Format

**Summary (1行目):** 英語で `#issue番号 実装した理由` の形式
- `#1 add chrome tab name tracking`
- `#2 fix electron app name resolution`
- `#3 add google calendar integration`

**Description (2行目以降):** 日本語で詳細な内容を記載
```
#1 add chrome tab name tracking

- Chrome のアクティブタブ名を1分間隔で記録
- AppleScript で tab title を取得
- activity_log テーブルに tab_title カラム追加
```

### Commit タイミングのルール

**適切な粒度で自律的にコミットすること。** 毎回のやり取りでコミットする必要はなく、ユーザーに確認を求める必要もない。以下の基準で判断する：

**コミットすべきタイミング:**
- 機能の追加・改善が完了し、**動作確認が取れた**とき
- 不具合の修正が完了し、**正常動作を確認した**とき
- リファクタリングや設定変更が一段落し、**既存機能が壊れていないことを確認した**とき

**🚫 鉄の掟: 動作しないコードを絶対にコミットしない**
- コミット前に必ず動作確認を行うこと
- ビルドエラー、実行時エラーが残った状態でのコミットは厳禁
- 中途半端な実装状態（機能が半分だけ動く等）でのコミットも禁止

**コミットしなくてよいタイミング:**
- 調査・検討段階（まだコード変更なし）
- 複数回のやり取りで段階的に実装中（完成前）
- 軽微な修正の途中で、まだ動作確認が済んでいない場合

## Debugging & Logs

```bash
# CLI モニタリング（詳細ログ付き）
python main.py monitor --verbose

# DB 直接確認
sqlite3 ~/.timetracker/timetracker.db "SELECT * FROM activity_log ORDER BY id DESC LIMIT 10;"

# AppleScript テスト
osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true'

# アイドル時間確認（ナノ秒）
ioreg -c IOHIDSystem | grep HIDIdleTime
```

## Important Files to Reference

- `README.md` - ユーザー向けドキュメント
- `config.yaml` - 全設定ファイル
- `requirements.txt` - Python 依存パッケージ
- `timetracker/monitor.py` - ウィンドウ検出ロジック（最も複雑）
- `timetracker/database.py` - DB スキーマ定義
- `timetracker/classifier.py` - 分類ルールエンジン

## Work Completion Policy (CRITICAL)

When completing complex tasks, **take all the time needed** and follow this rigorous process:

### 1. Investigation Phase
- Thoroughly understand the problem before implementing
- Check existing code, dependencies, and related components
- Identify root causes, not just symptoms
- Consider edge cases and failure scenarios

### 2. Solution Design Phase
- **Design multiple implementation approaches** (at least 2-3 alternatives)
- Document pros/cons for each approach
- Consider:
  - Correctness and maintainability
  - Performance implications
  - Type safety and error handling
  - Backward compatibility
  - Integration with existing code

### 3. Implementation Phase
- Implement the selected approach incrementally
- Add **detailed debug logging** to verify correctness
- Write clear, self-documenting code
- Handle error cases explicitly
- Use Python type annotations properly

### 4. Verification Phase (MANDATORY)
- **Build verification**: Ensure code runs without errors
- **Theoretical verification**: Validate logic with test cases on paper
- **Runtime verification**: Add logs to confirm behavior
- **Integration testing**: Check interactions with other components
- Document test cases and expected results

### 5. Completion Report (REQUIRED FORMAT)

Always provide a structured completion report in this format:

```
## 完了報告

### ユーザーから指示された内容
[Original user request summary]

### 生成AIエージェントが検討した実装案
#### 案1: [Approach name]
- [Description]
- 利点: [Pros]
- 欠点: [Cons]

#### 案2: [Approach name]
- [Description]
- 利点: [Pros]
- 欠点: [Cons]

### 各案に対する実装結果
#### 案1の実装:
- [What was implemented]
- 結果: [Outcome]
- 問題: [Issues encountered]

#### 案2の実装:
- [What was implemented]
- 結果: [Outcome]

### 実装した結果に対するテストした内容とその結果
#### テスト1: [Test name]
- [Test description]
- 結果: [Pass/Fail with details]

#### テスト2: [Test name]
- [Test description]
- 結果: [Pass/Fail with details]

### 最終的に採用した案とその理由
**案X ([Approach name]) を採用**

#### 採用理由:
1. [Reason 1]
2. [Reason 2]
3. [Reason 3]

#### 実装の詳細:
[Code snippets or explanation]

#### 効果:
- [Benefit 1]
- [Benefit 2]

#### コミット履歴:
[List of relevant commits]

**動作確認完了。[Next steps for user]**
```

### Key Principles

1. **Never rush**: "時間をかけて構わない" - Quality over speed
2. **Verify thoroughly**: Don't report completion until you've confirmed correctness
3. **Think systematically**: Consider alternatives, don't jump to the first solution
4. **Make it debuggable**: Add logs to verify behavior at runtime
5. **Document decisions**: Explain why you chose one approach over others
6. **Test comprehensively**: Build tests, theoretical tests, runtime tests
7. **Be honest**: If something doesn't work perfectly, document limitations

### Anti-Patterns to Avoid

- ❌ Reporting completion without verification
- ❌ Implementing the first idea without considering alternatives
- ❌ Skipping error handling or edge cases
- ❌ Not adding debug logs for complex logic
- ❌ Ignoring build errors or warnings
- ❌ Making assumptions without validation

**Remember**: The user values thorough, well-tested work over quick but incomplete solutions.
