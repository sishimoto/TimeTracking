#!/bin/bash
# =============================================================================
# TimeReaper リリーススクリプト
# =============================================================================
# ビルド → テスト → ローカルインストール → 起動 → 検証 → (GitHub Release)
# を一気通貫で実行します。
#
# 使い方:
#   ./scripts/release.sh                # テストビルド＋ローカル検証のみ
#   ./scripts/release.sh --prerelease   # テストビルド＋ローカル検証＋GitHub Pre-release
#   ./scripts/release.sh --release      # 正式リリース（バージョンアップ＋GitHub Release）
#   ./scripts/release.sh --skip-build   # ビルド済みの .app で検証のみ実行
#
# 検証項目:
#   1. pytest 全テスト通過
#   2. .app バンドルビルド＋検証
#   3. /Applications にインストール＋起動
#   4. ダッシュボード API ヘルスチェック
#   5. 権限チェック API 動作確認
#   6. アップデートチェック API 動作確認
#   7. DMG マウント＋アンマウントテスト
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# カラー出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${GREEN}✅ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }
log_section() { echo -e "\n${BLUE}${BOLD}=== $1 ===${NC}\n"; }
log_step()    { echo -e "${BOLD}▶ $1${NC}"; }

ERRORS=0
WARNINGS=0
fail() { log_error "$1"; ERRORS=$((ERRORS + 1)); }
warn() { log_warn "$1"; WARNINGS=$((WARNINGS + 1)); }

# --- オプション解析 ---
MODE="test"        # test | prerelease | release
SKIP_BUILD=false
DO_INSTALL=true

for arg in "$@"; do
    case $arg in
        --prerelease) MODE="prerelease" ;;
        --release)    MODE="release" ;;
        --skip-build) SKIP_BUILD=true ;;
        --no-install) DO_INSTALL=false ;;
        --help|-h)
            sed -n '2,/^$/s/^# //p' "$0"
            exit 0
            ;;
    esac
done

VERSION=$(python3 -c "import re; print(re.search(r\"__version__\s*=\s*['\\\"]([^'\\\"]+)\", open('timereaper/__init__.py').read()).group(1))")

echo ""
echo -e "${BOLD}⏱  TimeReaper Release Pipeline${NC}"
echo -e "${BOLD}   Version: ${VERSION}  Mode: ${MODE}${NC}"
echo "================================================"

# =============================================================================
# PHASE 1: ユニットテスト
# =============================================================================
log_section "PHASE 1: ユニットテスト"

log_step "pytest 実行中..."
source venv/bin/activate

if ./venv/bin/python -m pytest tests/ -q 2>&1; then
    log_info "全テスト通過"
else
    fail "テスト失敗"
    echo "テストを修正してから再実行してください。"
    exit 1
fi

# =============================================================================
# PHASE 2: ビルド
# =============================================================================
log_section "PHASE 2: ビルド"

if $SKIP_BUILD; then
    log_warn "ビルドスキップ (--skip-build)"
    if [ ! -d "dist/TimeReaper.app" ]; then
        fail "dist/TimeReaper.app が見つかりません"
        exit 1
    fi
else
    log_step "build.sh 実行中..."

    # 既存プロセスを停止
    pkill -f "TimeReaper.app" 2>/dev/null || true
    lsof -ti:5555 | xargs kill -9 2>/dev/null || true
    sleep 1

    case $MODE in
        prerelease) ./scripts/build.sh --prerelease --install 2>&1 | tail -20 ;;
        release)    ./scripts/build.sh --release --install 2>&1 | tail -20 ;;
        test)
            if $DO_INSTALL; then
                ./scripts/build.sh --dmg --install 2>&1 | tail -20
            else
                ./scripts/build.sh --dmg 2>&1 | tail -20
            fi
            ;;
    esac

    # ビルド結果チェック
    if [ -d "dist/TimeReaper.app" ]; then
        log_info ".app ビルド成功"
    else
        fail ".app ビルド失敗"
        exit 1
    fi

    # DMG 存在チェック
    DMG_FILE=$(ls -t dist/TimeReaper-*.dmg 2>/dev/null | head -1)
    if [ -n "$DMG_FILE" ]; then
        DMG_SIZE=$(du -sh "$DMG_FILE" | awk '{print $1}')
        log_info "DMG 作成成功: $DMG_FILE ($DMG_SIZE)"
    else
        warn "DMG ファイルが見つかりません"
    fi

    # バージョン再取得（release/prerelease 時にインクリメントされるため）
    VERSION=$(python3 -c "import re; print(re.search(r\"__version__\s*=\s*['\\\"]([^'\\\"]+)\", open('timereaper/__init__.py').read()).group(1))")
fi

# =============================================================================
# PHASE 3: DMG マウント/アンマウントテスト
# =============================================================================
log_section "PHASE 3: DMG テスト"

DMG_FILE=$(ls -t dist/TimeReaper-*.dmg 2>/dev/null | head -1)
if [ -n "$DMG_FILE" ]; then
    log_step "DMG マウントテスト: $DMG_FILE"
    MOUNT_DIR=$(mktemp -d /tmp/timereaper_dmgtest_XXXXX)

    if hdiutil attach "$DMG_FILE" -mountpoint "$MOUNT_DIR" -nobrowse -quiet 2>/dev/null; then
        # .app が含まれるか確認
        if [ -d "$MOUNT_DIR/TimeReaper.app" ]; then
            log_info "DMG 内に TimeReaper.app を確認"
        else
            fail "DMG 内に TimeReaper.app が見つかりません: $(ls "$MOUNT_DIR")"
        fi

        # アンマウント
        if hdiutil detach "$MOUNT_DIR" -quiet 2>/dev/null; then
            log_info "DMG アンマウント成功"
        else
            # force で再試行
            sleep 2
            if hdiutil detach "$MOUNT_DIR" -force -quiet 2>/dev/null; then
                warn "DMG アンマウント: force 必要"
            else
                fail "DMG アンマウント失敗"
            fi
        fi
    else
        fail "DMG マウント失敗"
    fi

    rm -rf "$MOUNT_DIR" 2>/dev/null || true
else
    warn "DMG ファイルなし — DMG テストスキップ"
fi

# =============================================================================
# PHASE 4: アプリ起動＋API 検証
# =============================================================================
log_section "PHASE 4: アプリ起動 & API 検証"

if $DO_INSTALL; then
    # 既存プロセスを確実に停止
    pkill -f "TimeReaper.app" 2>/dev/null || true
    lsof -ti:5555 | xargs kill -9 2>/dev/null || true
    sleep 2

    log_step "TimeReaper.app を起動中..."
    open /Applications/TimeReaper.app

    # サーバー起動を待機 (最大30秒)
    log_step "ダッシュボードの起動を待機中..."
    RETRY=0
    MAX_RETRY=30
    while [ $RETRY -lt $MAX_RETRY ]; do
        if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5555/api/version 2>/dev/null | grep -q "200"; then
            break
        fi
        sleep 1
        RETRY=$((RETRY + 1))
    done

    if [ $RETRY -ge $MAX_RETRY ]; then
        fail "ダッシュボードが30秒以内に起動しませんでした"
    else
        log_info "ダッシュボード起動確認 (${RETRY}秒)"

        # --- API 検証 ---
        echo ""

        # 4-1. バージョン API
        log_step "バージョン API チェック..."
        API_VERSION=$(curl -s http://127.0.0.1:5555/api/version | python3 -c "import sys,json; print(json.load(sys.stdin).get('version',''))" 2>/dev/null)
        if [ "$API_VERSION" = "$VERSION" ]; then
            log_info "バージョン API: v${API_VERSION}"
        else
            fail "バージョン不一致: API=${API_VERSION}, 期待=${VERSION}"
        fi

        # 4-2. 権限 API
        log_step "権限 API チェック..."
        PERM_RESULT=$(curl -s http://127.0.0.1:5555/api/permissions 2>/dev/null)
        if echo "$PERM_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'permissions' in d" 2>/dev/null; then
            # 各権限の状態を表示
            echo "$PERM_RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for p in d['permissions']:
    g = p['granted']
    icon = '✅' if g == True else '❌' if g == False else '❓'
    extra = ' [リクエスト可]' if p.get('can_request') else ''
    print(f'   {icon} {p[\"name\"]}: {g}{extra}')
" 2>/dev/null
            log_info "権限 API: 正常応答"
        else
            fail "権限 API: レスポンス不正"
        fi

        # 4-3. アップデートチェック API
        log_step "アップデートチェック API..."
        UPDATE_RESULT=$(curl -s http://127.0.0.1:5555/api/check-update 2>/dev/null)
        if echo "$UPDATE_RESULT" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
            log_info "アップデートチェック API: 正常応答"
        else
            fail "アップデートチェック API: レスポンス不正"
        fi

        # 4-4. 今日のサマリー API
        log_step "today API チェック..."
        TODAY_RESULT=$(curl -s http://127.0.0.1:5555/api/today 2>/dev/null)
        if echo "$TODAY_RESULT" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
            log_info "today API: 正常応答"
        else
            fail "today API: レスポンス不正"
        fi

        # 4-5. 設定 API
        log_step "設定 API チェック..."
        SETTINGS_RESULT=$(curl -s http://127.0.0.1:5555/api/settings 2>/dev/null)
        if echo "$SETTINGS_RESULT" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
            log_info "設定 API: 正常応答"
        else
            fail "設定 API: レスポンス不正"
        fi

        # 4-6. ページレンダリングチェック
        log_step "ページレンダリングチェック..."
        for page in "/" "/summary/$(date +%Y-%m-%d)" "/weekly" "/settings"; do
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5555${page}" 2>/dev/null)
            if [ "$HTTP_CODE" = "200" ]; then
                log_info "  ${page}: 200 OK"
            else
                fail "  ${page}: HTTP ${HTTP_CODE}"
            fi
        done
    fi
else
    warn "インストールスキップ — API 検証スキップ"
fi

# =============================================================================
# PHASE 5: 通知テスト
# =============================================================================
log_section "PHASE 5: 通知テスト"

if $DO_INSTALL && [ $RETRY -lt $MAX_RETRY ] 2>/dev/null; then
    log_step "テスト通知送信..."
    NOTIF_RESULT=$(curl -s -X POST http://127.0.0.1:5555/api/request-notification-permission 2>/dev/null)
    NOTIF_SUCCESS=$(echo "$NOTIF_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))" 2>/dev/null)
    if [ "$NOTIF_SUCCESS" = "True" ]; then
        log_info "テスト通知: 送信成功（macOS 通知センターを確認してください）"
    else
        warn "テスト通知: 送信失敗 — $(echo "$NOTIF_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error',''))" 2>/dev/null)"
    fi
else
    warn "通知テストスキップ"
fi

# =============================================================================
# PHASE 6: 結果サマリー
# =============================================================================
log_section "結果サマリー"

echo ""
echo -e "  バージョン:  ${BOLD}v${VERSION}${NC}"
echo -e "  モード:      ${BOLD}${MODE}${NC}"
echo -e "  エラー:      ${ERRORS} 件"
echo -e "  警告:        ${WARNINGS} 件"
echo ""

if [ $ERRORS -gt 0 ]; then
    log_error "リリース検証に失敗しました（${ERRORS} 件のエラー）"
    echo ""
    echo "エラーを修正してから再実行してください:"
    echo "  ./scripts/release.sh"
    exit 1
fi

if [ $WARNINGS -gt 0 ]; then
    log_warn "警告がありますが、リリース可能です"
fi

log_info "リリース検証完了 🎉"
echo ""

# GitHub Release が作成された場合の URL
if [ "$MODE" = "prerelease" ] || [ "$MODE" = "release" ]; then
    if [ "$MODE" = "prerelease" ]; then
        TAG="v${VERSION}-rc"
    else
        TAG="v${VERSION}"
    fi
    echo -e "  ${BOLD}GitHub Release:${NC} https://github.com/sishimoto/TimeReaper/releases/tag/${TAG}"
    echo ""
fi

echo "次のステップ:"
if [ "$MODE" = "test" ]; then
    echo "  1. ブラウザで http://127.0.0.1:5555 を開いて手動確認"
    echo "  2. 問題なければプレリリース: ./scripts/release.sh --prerelease"
    echo "  3. 正式リリース: ./scripts/release.sh --release"
else
    echo "  1. ブラウザで http://127.0.0.1:5555 を開いて手動確認"
    echo "  2. 別端末でアップデートテスト: 旧バージョンからアップデートを実行"
fi
echo ""
