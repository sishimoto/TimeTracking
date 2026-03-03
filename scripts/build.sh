#!/bin/bash
# TimeReaper ビルドスクリプト
# macOS .app バンドルをビルドし、配布用の DMG を作成します。
#
# 使い方:
#   ./scripts/build.sh           # .app ビルド
#   ./scripts/build.sh --dmg     # .app + DMG 作成
#   ./scripts/build.sh --clean   # クリーンビルド
#   ./scripts/build.sh --verify  # ビルド後の検証のみ

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}✅ $1${NC}"; }
log_warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

# バージョン取得
VERSION=$(python3 -c "import re; content=open('timereaper/__init__.py').read(); print(re.search(r\"__version__\s*=\s*['\\\"]([^'\\\"]+)\", content).group(1))")
echo ""
echo "⏱  TimeReaper Build v${VERSION}"
echo "================================"
echo ""

# オプション解析
DO_CLEAN=false
DO_DMG=false
DO_VERIFY_ONLY=false
DO_RELEASE=false
DO_PRERELEASE=false
DO_INSTALL=false

for arg in "$@"; do
    case $arg in
        --clean) DO_CLEAN=true ;;
        --dmg) DO_DMG=true ;;
        --verify) DO_VERIFY_ONLY=true ;;
        --release) DO_RELEASE=true; DO_DMG=true; DO_CLEAN=true ;;
        --prerelease) DO_PRERELEASE=true; DO_DMG=true; DO_CLEAN=true ;;
        --install) DO_INSTALL=true ;;
        --help|-h)
            echo "使い方: $0 [--clean] [--dmg] [--verify] [--release] [--prerelease] [--install]"
            echo ""
            echo "  --clean       クリーンビルド（build/, dist/ を削除してからビルド）"
            echo "  --dmg         DMG ファイルも作成"
            echo "  --verify      既存ビルドの検証のみ"
            echo "  --release     正式リリース（クリーンビルド + DMG + タグ + GitHub Release）"
            echo "  --prerelease  テスト用プレリリース（クリーンビルド + DMG + タグ + GitHub Pre-release）"
            echo "  --install     ビルド後に /Applications にインストール"
            echo ""
            echo "例:"
            echo "  $0 --prerelease --install  # プレリリース作成 + ローカルインストール"
            echo "  $0 --release               # 正式リリース作成"
            exit 0
            ;;
    esac
done

# 検証のみモード
if $DO_VERIFY_ONLY; then
    echo "🔍 ビルド検証..."
    APP_PATH="dist/TimeReaper.app"
    if [ ! -d "$APP_PATH" ]; then
        log_error "dist/TimeReaper.app が見つかりません。先にビルドしてください。"
        exit 1
    fi
    # 検証セクションにジャンプ
    SKIP_BUILD=true
else
    SKIP_BUILD=false
fi

if ! $SKIP_BUILD; then

    # 前提条件チェック
    echo "🔍 前提条件チェック..."

    # Python チェック
    if [ ! -f "venv/bin/python" ]; then
        log_error "venv が見つかりません。先に setup.sh を実行してください。"
        exit 1
    fi
    source venv/bin/activate
    log_info "Python: $(python --version)"

    # py2app チェック
    if ! python -c "import py2app" 2>/dev/null; then
        echo "📦 py2app をインストール中..."
        pip install py2app
    fi
    log_info "py2app: インストール済み"

    # 必須ファイルチェック
    for f in main.py config.yaml timereaper/__init__.py timereaper/templates/dashboard.html timereaper/templates/summary.html timereaper/templates/weekly.html timereaper/templates/settings.html; do
        if [ ! -f "$f" ]; then
            log_error "必須ファイルが見つかりません: $f"
            exit 1
        fi
    done
    log_info "必須ファイル: OK"

    # アイコンチェック
    if [ -f "assets/AppIcon.icns" ]; then
        log_info "アプリアイコン: assets/AppIcon.icns"
    else
        log_warn "アイコンファイルがありません（デフォルトアイコンを使用）"
        echo "   アイコンを生成するには: python scripts/generate_icon.py"
    fi

    # クリーンビルド
    if $DO_CLEAN; then
        echo ""
        echo "🧹 クリーンビルド..."
        rm -rf build dist
        log_info "build/ と dist/ を削除しました"
    fi

    # ビルド実行
    echo ""
    echo "🔨 .app バンドルをビルド中..."
    python setup.py py2app 2>&1 | tail -5

    if [ ! -d "dist/TimeReaper.app" ]; then
        log_error "ビルドに失敗しました"
        exit 1
    fi
    log_info ".app バンドルをビルドしました: dist/TimeReaper.app"

    # CalHelper.app を同梱
    if [ -d "CalHelper.app" ] && [ -f "CalHelper.app/Contents/MacOS/CalHelper" ]; then
        echo ""
        echo "📅 CalHelper.app を同梱中..."
        HELPERS_DIR="dist/TimeReaper.app/Contents/Resources/CalHelper.app"
        cp -R CalHelper.app "$HELPERS_DIR"
        log_info "CalHelper.app を同梱しました"
    else
        log_warn "CalHelper.app が見つかりません（Mac Calendar 連携は無効）"
    fi

    # config.yaml が Resources に含まれるか確認
    if [ -f "dist/TimeReaper.app/Contents/Resources/config.yaml" ]; then
        log_info "config.yaml: 同梱済み"
    else
        log_warn "config.yaml が .app に含まれていません。手動でコピーします..."
        cp config.yaml "dist/TimeReaper.app/Contents/Resources/config.yaml"
        log_info "config.yaml をコピーしました"
    fi

fi  # SKIP_BUILD

# ===== ビルド検証 =====
echo ""
echo "🔍 ビルド検証..."
APP_PATH="dist/TimeReaper.app"
ERRORS=0

# 1. .app バンドル構造
echo "  - バンドル構造..."
for check_dir in Contents Contents/MacOS Contents/Resources; do
    if [ ! -d "$APP_PATH/$check_dir" ]; then
        log_error "    $check_dir が見つかりません"
        ERRORS=$((ERRORS + 1))
    fi
done

# 2. 実行ファイル
if [ -x "$APP_PATH/Contents/MacOS/TimeReaper" ]; then
    log_info "  実行ファイル: OK"
else
    log_error "  実行ファイルが見つかりません"
    ERRORS=$((ERRORS + 1))
fi

# 3. Info.plist のバージョン
PLIST_VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP_PATH/Contents/Info.plist" 2>/dev/null || echo "MISSING")
if [ "$PLIST_VERSION" = "$VERSION" ]; then
    log_info "  plist バージョン: $PLIST_VERSION"
else
    log_error "  plist バージョン不一致: $PLIST_VERSION (期待: $VERSION)"
    ERRORS=$((ERRORS + 1))
fi

# 4. テンプレートファイル
for tmpl in dashboard.html summary.html weekly.html settings.html; do
    if find "$APP_PATH" -name "$tmpl" | grep -q .; then
        log_info "  テンプレート $tmpl: OK"
    else
        log_error "  テンプレート $tmpl が見つかりません"
        ERRORS=$((ERRORS + 1))
    fi
done

# 5. 署名チェック（ベストエフォート）
if codesign -v "$APP_PATH" 2>/dev/null; then
    log_info "  コード署名: OK"
else
    log_warn "  コード署名: なし（配布時は署名を推奨）"
fi

# 結果
echo ""
if [ $ERRORS -eq 0 ]; then
    APP_SIZE=$(du -sh "$APP_PATH" | awk '{print $1}')
    log_info "ビルド検証: 全チェック通過 (サイズ: $APP_SIZE)"
else
    log_error "ビルド検証: $ERRORS 件のエラー"
    exit 1
fi

# DMG 作成
if $DO_DMG; then
    echo ""
    echo "💿 DMG を作成中..."

    # プレリリース時はサフィックス付き
    if $DO_PRERELEASE; then
        DMG_NAME="TimeReaper-v${VERSION}-rc.dmg"
    else
        DMG_NAME="TimeReaper-v${VERSION}.dmg"
    fi
    DMG_PATH="dist/$DMG_NAME"

    # 既存 DMG を削除
    rm -f "$DMG_PATH"

    # 一時ディレクトリに配置
    DMG_STAGING="dist/dmg_staging"
    rm -rf "$DMG_STAGING"
    mkdir -p "$DMG_STAGING"
    cp -R "$APP_PATH" "$DMG_STAGING/"

    # Applications フォルダへのシンボリックリンク
    ln -s /Applications "$DMG_STAGING/Applications"

    # DMG 作成
    hdiutil create -volname "TimeReaper v${VERSION}" \
        -srcfolder "$DMG_STAGING" \
        -ov -format UDZO \
        "$DMG_PATH"

    rm -rf "$DMG_STAGING"

    if [ -f "$DMG_PATH" ]; then
        DMG_SIZE=$(du -sh "$DMG_PATH" | awk '{print $1}')
        log_info "DMG を作成しました: $DMG_PATH ($DMG_SIZE)"
    else
        log_error "DMG 作成に失敗しました"
        exit 1
    fi
fi

# GitHub Release / Pre-release 作成
if $DO_RELEASE || $DO_PRERELEASE; then
    echo ""

    # gh CLI チェック
    if ! command -v gh &>/dev/null; then
        log_error "gh CLI がインストールされていません: brew install gh"
        exit 1
    fi

    if $DO_PRERELEASE; then
        TAG="v${VERSION}-rc"
        RELEASE_TITLE="v${VERSION}-rc: テスト用プレリリース"
        RELEASE_FLAGS="--prerelease"
        echo "📦 Pre-release を作成中..."
    else
        TAG="v${VERSION}"
        RELEASE_TITLE="v${VERSION}"
        RELEASE_FLAGS=""
        echo "📦 正式リリースを作成中..."
    fi

    # 既存の同名リリースがあれば削除
    if gh release view "$TAG" &>/dev/null; then
        echo "  既存リリース $TAG を削除中..."
        gh release delete "$TAG" --yes --cleanup-tag 2>/dev/null || true
        git tag -d "$TAG" 2>/dev/null || true
    fi

    # コミット（未コミットの変更がある場合）
    if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet HEAD 2>/dev/null; then
        echo "  未コミットの変更をコミット中..."
        git add -A
        if $DO_PRERELEASE; then
            git commit -m "prerelease: v${VERSION}-rc" --allow-empty
        else
            git commit -m "release: v${VERSION}" --allow-empty
        fi
    fi

    # プッシュ
    git push origin main 2>/dev/null || true

    # タグ作成 & プッシュ
    git tag -a "$TAG" -m "$RELEASE_TITLE"
    git push origin "$TAG"

    # GitHub Release 作成 + DMG アップロード
    gh release create "$TAG" "$DMG_PATH" \
        --title "$RELEASE_TITLE" \
        --notes "ビルド日時: $(date '+%Y-%m-%d %H:%M')" \
        $RELEASE_FLAGS

    log_info "GitHub Release を作成しました: $TAG"
    echo "  URL: https://github.com/sishimoto/TimeReaper/releases/tag/$TAG"
fi

# /Applications にインストール
if $DO_INSTALL; then
    echo ""
    echo "📲 /Applications にインストール中..."

    # 既存アプリを停止
    pkill -f "TimeReaper.app" 2>/dev/null || true
    lsof -ti:5555 | xargs kill -9 2>/dev/null || true
    sleep 2

    # 既存アプリを削除してコピー
    rm -rf /Applications/TimeReaper.app
    cp -R dist/TimeReaper.app /Applications/
    log_info "/Applications/TimeReaper.app にインストールしました"

    echo ""
    echo "起動方法:"
    echo "  open /Applications/TimeReaper.app"
fi

echo ""
echo "🎉 完了！"
echo ""
if ! $DO_INSTALL; then
    echo "テスト実行:"
    echo "  open dist/TimeReaper.app"
    echo ""
fi
