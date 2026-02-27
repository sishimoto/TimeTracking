#!/bin/bash
# TimeTracker セットアップスクリプト
# macOS用の稼働時間管理アプリのセットアップを行います

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# --install-agent オプション: LaunchAgent のインストールのみ実行
if [ "$1" = "--install-agent" ]; then
    echo "🚀 LaunchAgent をインストール中..."
    PLIST_SRC="$SCRIPT_DIR/com.timetracker.app.plist.template"
    PLIST_DST="$HOME/Library/LaunchAgents/com.timetracker.app.plist"
    VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"

    if [ ! -f "$VENV_PYTHON" ]; then
        echo "❌ venv が見つかりません。先に ./setup.sh を実行してください。"
        exit 1
    fi

    # 既存の LaunchAgent を停止
    launchctl unload "$PLIST_DST" 2>/dev/null || true

    # テンプレートからplistを生成
    sed -e "s|__VENV_PYTHON__|$VENV_PYTHON|g" \
        -e "s|__PROJECT_DIR__|$SCRIPT_DIR|g" \
        -e "s|__HOME__|$HOME|g" \
        "$PLIST_SRC" > "$PLIST_DST"

    # LaunchAgent を登録
    launchctl load "$PLIST_DST"

    echo "✅ LaunchAgent をインストールしました"
    echo "   macOS ログイン時に自動起動します"
    echo ""
    echo "   停止: launchctl unload ~/Library/LaunchAgents/com.timetracker.app.plist"
    echo "   再開: launchctl load ~/Library/LaunchAgents/com.timetracker.app.plist"
    echo "   削除: launchctl unload ~/Library/LaunchAgents/com.timetracker.app.plist && rm ~/Library/LaunchAgents/com.timetracker.app.plist"
    exit 0
fi

echo "⏱ TimeTracker セットアップ"
echo "=========================="
echo ""

# Python バージョンチェック
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Pythonがインストールされていません"
    echo "   brew install python3 でインストールしてください"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "✅ Python: $PYTHON_VERSION"

# 仮想環境の作成
if [ ! -d "venv" ]; then
    echo ""
    echo "📦 仮想環境を作成中..."
    $PYTHON_CMD -m venv venv
    echo "✅ 仮想環境を作成しました"
fi

# 仮想環境の有効化
source venv/bin/activate
echo "✅ 仮想環境を有効化しました"

# 依存パッケージのインストール
echo ""
echo "📦 依存パッケージをインストール中..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyyaml  # config用
echo "✅ 依存パッケージをインストールしました"

# データディレクトリの作成
DATA_DIR="$HOME/.timetracker"
if [ ! -d "$DATA_DIR" ]; then
    mkdir -p "$DATA_DIR"
    echo "✅ データディレクトリを作成しました: $DATA_DIR"
fi

# macOS アクセシビリティ権限の案内
echo ""
echo "⚠️  重要: macOSのアクセシビリティ権限が必要です"
echo ""
echo "   TimeTrackerがウィンドウ情報を取得するには、以下の設定が必要です:"
echo ""
echo "   1. システム設定 → プライバシーとセキュリティ → アクセシビリティ"
echo "   2. 「Terminal」または「iTerm2」（使用中のターミナル）を有効にする"
echo "   3. macOS 14以降の場合、「画面収録」の権限も必要な場合があります"
echo ""

# CalHelper.app のビルド（Mac Calendar 連携用）
if [ -f "CalHelper.swift" ]; then
    echo ""
    echo "📅 CalHelper.app をビルド中..."
    mkdir -p CalHelper.app/Contents/MacOS
    if [ ! -f "CalHelper.app/Contents/Info.plist" ]; then
        cat > CalHelper.app/Contents/Info.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.timetracker.calhelper</string>
    <key>CFBundleName</key>
    <string>CalHelper</string>
    <key>CFBundleExecutable</key>
    <string>CalHelper</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSBackgroundOnly</key>
    <true/>
    <key>NSCalendarsFullAccessUsageDescription</key>
    <string>TimeTracker needs calendar access to show your schedule.</string>
</dict>
</plist>
PLIST
    fi
    swiftc -framework Cocoa -framework EventKit CalHelper.swift -o CalHelper.app/Contents/MacOS/CalHelper
    echo "✅ CalHelper.app をビルドしました"
else
    echo "⚠️  CalHelper.swift が見つかりません。Mac Calendar 連携は無効です。"
fi

# データベースの初期化
echo "🗃  データベースを初期化中..."
$PYTHON_CMD -c "
import sys
sys.path.insert(0, '.')
from timetracker.config import load_config, ensure_data_dir
from timetracker.database import init_db
load_config()
ensure_data_dir()
init_db()
print('✅ データベースを初期化しました')
"

echo ""
echo "🎉 セットアップ完了！"
echo ""
echo "起動方法:"
echo ""
echo "  方法1: スクリプトで起動"
echo "    ./start.sh"
echo ""
echo "  方法2: ターミナルから起動"
echo "    source venv/bin/activate && python main.py start"
echo ""
echo "  方法3: macOS ログイン時に自動起動（LaunchAgent）"
echo "    ./setup.sh --install-agent"
echo ""
echo "  ダッシュボードURL: http://127.0.0.1:5555"
echo ""
