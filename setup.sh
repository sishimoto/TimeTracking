#!/bin/bash
# TimeReaper セットアップスクリプト
# macOS用の稼働時間管理アプリのセットアップを行います
#
# 使い方:
#   ./setup.sh                 # フルセットアップ
#   ./setup.sh --install-agent # LaunchAgent のインストールのみ
#   ./setup.sh --update        # 依存パッケージの更新のみ
#   ./setup.sh --help          # ヘルプ

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}✅ $1${NC}"; }
log_warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }
log_step()  { echo -e "\n${GREEN}$1${NC}"; }

# バージョン取得
get_version() {
    python3 -c "
import re
with open('timereaper/__init__.py') as f:
    m = re.search(r\"__version__\s*=\s*['\\\"]([^'\\\"]+)\", f.read())
    print(m.group(1) if m else '0.0.0')
" 2>/dev/null || echo "0.0.0"
}

# ヘルプ
show_help() {
    echo "⏱  TimeReaper セットアップスクリプト"
    echo ""
    echo "使い方: $0 [オプション]"
    echo ""
    echo "オプション:"
    echo "  (なし)           フルセットアップ（venv + 依存パッケージ + CalHelper + DB初期化）"
    echo "  --install-agent  LaunchAgent のインストールのみ"
    echo "  --update         依存パッケージの更新のみ（venv が既にある場合）"
    echo "  --help, -h       このヘルプを表示"
    exit 0
}

# --help
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    show_help
fi

# --install-agent オプション: LaunchAgent のインストールのみ実行
if [ "$1" = "--install-agent" ]; then
    echo "🚀 LaunchAgent をインストール中..."
    PLIST_SRC="$SCRIPT_DIR/com.timereaper.app.plist.template"
    PLIST_DST="$HOME/Library/LaunchAgents/com.timereaper.app.plist"
    VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"

    if [ ! -f "$PLIST_SRC" ]; then
        log_error "テンプレートファイルが見つかりません: $PLIST_SRC"
        exit 1
    fi

    if [ ! -f "$VENV_PYTHON" ]; then
        log_error "venv が見つかりません。先に ./setup.sh を実行してください。"
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

    log_info "LaunchAgent をインストールしました"
    echo "   macOS ログイン時に自動起動します"
    echo ""
    echo "   停止: launchctl unload ~/Library/LaunchAgents/com.timereaper.app.plist"
    echo "   再開: launchctl load ~/Library/LaunchAgents/com.timereaper.app.plist"
    echo "   削除: launchctl unload ~/Library/LaunchAgents/com.timereaper.app.plist && rm ~/Library/LaunchAgents/com.timereaper.app.plist"
    exit 0
fi

# --update オプション: 依存パッケージの更新のみ
if [ "$1" = "--update" ]; then
    if [ ! -d "venv" ]; then
        log_error "venv が見つかりません。先に ./setup.sh を実行してください。"
        exit 1
    fi
    source venv/bin/activate
    log_step "📦 依存パッケージを更新中..."
    pip install --upgrade pip
    pip install -r requirements.txt --upgrade
    log_info "依存パッケージを更新しました"
    VERSION=$(get_version)
    echo "   TimeReaper v${VERSION}"
    exit 0
fi

echo "⏱ TimeReaper セットアップ"
echo "=========================="
echo ""

# macOS チェック
if [ "$(uname)" != "Darwin" ]; then
    log_error "このアプリは macOS 専用です"
    exit 1
fi

# macOS バージョン確認
MACOS_VERSION=$(sw_vers -productVersion)
echo "   macOS: $MACOS_VERSION"

# Python バージョンチェック
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON_CMD="$cmd"
        break
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    if command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        log_error "Python 3 がインストールされていません"
        echo "   brew install python3 でインストールしてください"
        exit 1
    fi
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    log_error "Python 3.10 以上が必要です（現在: $PYTHON_VERSION）"
    exit 1
fi
log_info "Python: $PYTHON_VERSION ($PYTHON_CMD)"

# 仮想環境の作成
if [ -d "venv" ]; then
    log_info "仮想環境: 既存のものを使用"
else
    log_step "📦 仮想環境を作成中..."
    $PYTHON_CMD -m venv venv
    log_info "仮想環境を作成しました"
fi

# 仮想環境の有効化
source venv/bin/activate
log_info "仮想環境を有効化しました"

# 依存パッケージのインストール
log_step "📦 依存パッケージをインストール中..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
log_info "依存パッケージをインストールしました"

# データディレクトリの作成
DATA_DIR="$HOME/.timereaper"
mkdir -p "$DATA_DIR"
log_info "データディレクトリ: $DATA_DIR"

# macOS アクセシビリティ権限の案内
echo ""
echo "⚠️  重要: macOSのアクセシビリティ権限が必要です"
echo ""
echo "   TimeReaperがウィンドウ情報を取得するには、以下の設定が必要です:"
echo ""
echo "   1. システム設定 → プライバシーとセキュリティ → アクセシビリティ"
echo "   2. 「Terminal」または「iTerm2」（使用中のターミナル）を有効にする"
echo "   3. macOS 14以降の場合、「画面収録」の権限も必要な場合があります"
echo ""

# CalHelper.app のビルド（Mac Calendar 連携用）
if [ -f "CalHelper.swift" ]; then
    log_step "📅 CalHelper.app をビルド中..."
    mkdir -p CalHelper.app/Contents/MacOS
    if [ ! -f "CalHelper.app/Contents/Info.plist" ]; then
        cat > CalHelper.app/Contents/Info.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.timereaper.calhelper</string>
    <key>CFBundleName</key>
    <string>CalHelper</string>
    <key>CFBundleExecutable</key>
    <string>CalHelper</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSBackgroundOnly</key>
    <true/>
    <key>NSCalendarsFullAccessUsageDescription</key>
    <string>TimeReaper needs calendar access to show your schedule.</string>
</dict>
</plist>
PLIST
    fi
    swiftc -framework Cocoa -framework EventKit CalHelper.swift -o CalHelper.app/Contents/MacOS/CalHelper 2>/dev/null
    if [ $? -eq 0 ]; then
        log_info "CalHelper.app をビルドしました"
    else
        log_warn "CalHelper.app のビルドに失敗しました（Xcode Command Line Tools が必要です）"
    fi
else
    log_warn "CalHelper.swift が見つかりません。Mac Calendar 連携は無効です。"
fi

# データベースの初期化
log_step "🗃  データベースを初期化中..."
$PYTHON_CMD -c "
import sys
sys.path.insert(0, '.')
from timereaper.config import load_config, ensure_data_dir
from timereaper.database import init_db
load_config()
ensure_data_dir()
init_db()
" 2>/dev/null
log_info "データベースを初期化しました"

VERSION=$(get_version)

echo ""
echo "🎉 セットアップ完了！ (v${VERSION})"
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
