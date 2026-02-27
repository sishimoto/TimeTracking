#!/bin/bash
# TimeTracker セットアップスクリプト
# macOS用の稼働時間管理アプリのセットアップを行います

set -e

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
echo "使い方:"
echo "  # 仮想環境を有効化"
echo "  source venv/bin/activate"
echo ""
echo "  # メニューバーアプリとして起動（推奨）"
echo "  python main.py start"
echo ""
echo "  # CLIモードでモニタリング（テスト用）"
echo "  python main.py monitor"
echo ""
echo "  # ダッシュボードのみ起動"
echo "  python main.py dashboard"
echo ""
echo "  # ダッシュボードURL: http://127.0.0.1:5555"
echo ""
