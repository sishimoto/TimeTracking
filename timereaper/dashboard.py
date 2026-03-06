"""
Webダッシュボード - Flask API
アクティビティデータを可視化するためのREST APIとダッシュボードを提供します。
"""

import os
from datetime import date, timedelta, datetime
from flask import Flask, jsonify, request, render_template, send_from_directory, send_file, after_this_request
from flask_cors import CORS
import requests
from typing import Any

from .config import get_config
from .database import (
    get_activities,
    get_daily_summary,
    get_timeline,
    get_hourly_breakdown,
    get_project_summary,
    get_calendar_events,
    get_weekly_trend,
    get_weekly_report,
    get_monthly_report,
    update_activity_tags,
    update_activity_tags_by_time,
    get_time_blocks,
)

# グローバル: ポモドーロタイマーインスタンス（メニューバーアプリから設定される）
_pomodoro_timer = None
_settings_change_callback = None


def set_pomodoro_timer(timer):
    """メニューバーアプリからポモドーロタイマーを登録する"""
    global _pomodoro_timer
    _pomodoro_timer = timer


def set_settings_change_callback(callback):
    """設定変更時のコールバックを登録する"""
    global _settings_change_callback
    _settings_change_callback = callback


def _get_pomodoro_timer():
    return _pomodoro_timer


def _notify_settings_changed(settings):
    if _settings_change_callback:
        try:
            _settings_change_callback(settings)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"設定変更通知エラー: {e}")


def create_app():
    """Flaskアプリケーションを生成する"""
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    static_dir = os.path.join(os.path.dirname(__file__), "static")

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
    )
    CORS(app)

    # --- ページルート ---
    @app.route("/")
    def index():
        return render_template("dashboard.html")

    # --- API ルート ---
    @app.route("/api/today")
    def api_today():
        """今日のサマリー"""
        today = date.today().isoformat()
        summary = get_daily_summary(today)
        timeline = get_timeline(today)
        hourly = get_hourly_breakdown(today)
        events = get_calendar_events(today)

        # 合計作業時間を計算
        total_seconds = sum(r.get("total_seconds", 0) for r in summary)
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)

        return jsonify({
            "date": today,
            "total_work_time": f"{hours}h {minutes}m",
            "total_seconds": total_seconds,
            "summary": summary,
            "timeline": timeline,
            "hourly": hourly,
            "calendar_events": events,
        })

    @app.route("/api/activities")
    def api_activities():
        """アクティビティログの取得"""
        start = request.args.get("start")
        end = request.args.get("end")
        app_name = request.args.get("app")
        project = request.args.get("project")
        limit = request.args.get("limit", 500, type=int)

        activities = get_activities(start, end, app_name, project, limit)
        return jsonify({"activities": activities})

    @app.route("/api/daily/<target_date>")
    def api_daily(target_date):
        """指定日のサマリー"""
        summary = get_daily_summary(target_date)
        timeline = get_timeline(target_date)
        hourly = get_hourly_breakdown(target_date)
        events = get_calendar_events(target_date)

        total_seconds = sum(r.get("total_seconds", 0) for r in summary)
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)

        return jsonify({
            "date": target_date,
            "total_work_time": f"{hours}h {minutes}m",
            "total_seconds": total_seconds,
            "summary": summary,
            "timeline": timeline,
            "hourly": hourly,
            "calendar_events": events,
        })

    @app.route("/api/projects")
    def api_projects():
        """プロジェクトサマリー"""
        start = request.args.get("start")
        end = request.args.get("end")
        summary = get_project_summary(start, end)
        return jsonify({"projects": summary})

    @app.route("/api/weekly")
    def api_weekly():
        """週次トレンド"""
        weeks = request.args.get("weeks", 4, type=int)
        trend = get_weekly_trend(weeks)
        return jsonify({"weekly_trend": trend})

    @app.route("/api/hourly/<target_date>")
    def api_hourly(target_date):
        """時間帯ごとの内訳"""
        hourly = get_hourly_breakdown(target_date)
        return jsonify({"hourly": hourly})

    @app.route("/api/tag-options")
    def api_tag_options():
        """タグ編集用の選択肢を返す"""
        cfg = get_config()
        rules = cfg.get("classification_rules", {})
        return jsonify({
            "task_categories": rules.get("task_categories", []),
            "cost_categories": rules.get("cost_categories", []),
        })

    @app.route("/api/update-tags", methods=["POST"])
    def api_update_tags():
        """アクティビティのタグを一括更新する"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        start_time = data.get("start_time")
        end_time = data.get("end_time")
        app_name = data.get("app_name")
        work_phase = data.get("work_phase")
        project = data.get("project")

        if not start_time or not end_time or not app_name:
            return jsonify({"error": "start_time, end_time, app_name are required"}), 400

        updated = update_activity_tags(
            start_time=start_time,
            end_time=end_time,
            app_name=app_name,
            work_phase=work_phase,
            project=project,
        )
        return jsonify({"updated": updated})

    # --- 日次サマリーページ ---
    @app.route("/summary")
    @app.route("/summary/<target_date>")
    def summary_page(target_date=None):
        """10分ブロック単位のタグ一括編集ページ"""
        if target_date is None:
            target_date = date.today().isoformat()
        return render_template("summary.html", target_date=target_date)

    # --- 週次レポートページ ---
    @app.route("/weekly")
    @app.route("/weekly/<target_date>")
    def weekly_page(target_date=None):
        """週次レポートページ"""
        if target_date is None:
            target_date = date.today().isoformat()
        return render_template("weekly.html", target_date=target_date)

    @app.route("/api/weekly-report/<target_date>")
    def api_weekly_report(target_date):
        """指定日を含む週の詳細レポートを返す"""
        report = get_weekly_report(target_date)
        return jsonify(report)

    @app.route("/api/time-blocks/<target_date>")
    def api_time_blocks(target_date):
        """10分ブロックにまとめたサマリーを返す"""
        block_minutes = request.args.get("block_minutes", 10, type=int)
        blocks = get_time_blocks(target_date, block_minutes)
        return jsonify({"date": target_date, "blocks": blocks})

    @app.route("/api/update-block-tags", methods=["POST"])
    def api_update_block_tags():
        """10分ブロック単位でタグを一括更新する（アプリ不問）"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        start_time = data.get("start_time")
        end_time = data.get("end_time")
        work_phase = data.get("work_phase")
        project = data.get("project")

        if not start_time or not end_time:
            return jsonify({"error": "start_time and end_time are required"}), 400

        updated = update_activity_tags_by_time(
            start_time=start_time,
            end_time=end_time,
            work_phase=work_phase,
            project=project,
        )
        return jsonify({"updated": updated})

    @app.route("/api/add-tag", methods=["POST"])
    def api_add_tag():
        """タグカテゴリに新しい値を追加する"""
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        category = data.get("category")  # "task_categories" or "cost_categories"
        value = data.get("value", "").strip()

        if category not in ("task_categories", "cost_categories"):
            return jsonify({"error": "category must be task_categories or cost_categories"}), 400
        if not value:
            return jsonify({"error": "value is required"}), 400

        from .config import add_tag_to_config
        success = add_tag_to_config(category, value)
        if success:
            return jsonify({"ok": True, "message": f"Added '{value}' to {category}"})
        else:
            return jsonify({"ok": False, "message": f"'{value}' already exists in {category}"})

    # --- エクスポート API ---
    @app.route("/api/export/daily/<target_date>")
    def api_export_daily(target_date):
        """日次サマリーをエクスポートする（format=md|pdf）"""
        from flask import Response
        fmt = request.args.get("format", "md")

        if fmt == "pdf":
            from .exporter import export_daily_pdf
            pdf_data = export_daily_pdf(target_date)
            return Response(
                pdf_data,
                mimetype="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''日次サマリー_{target_date}.pdf",
                },
            )
        else:
            from .exporter import export_daily_markdown
            md_text = export_daily_markdown(target_date)
            return Response(
                md_text,
                mimetype="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''日次サマリー_{target_date}.md",
                },
            )

    @app.route("/api/export/monthly/<int:year>/<int:month>")
    def api_export_monthly(year, month):
        """月次サマリーをエクスポートする（format=md|pdf）"""
        from flask import Response
        fmt = request.args.get("format", "md")

        if month < 1 or month > 12:
            return jsonify({"error": "month must be 1-12"}), 400

        if fmt == "pdf":
            from .exporter import export_monthly_pdf
            pdf_data = export_monthly_pdf(year, month)
            return Response(
                pdf_data,
                mimetype="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''月次サマリー_{year}年{month:02d}月.pdf",
                },
            )
        else:
            from .exporter import export_monthly_markdown
            md_text = export_monthly_markdown(year, month)
            return Response(
                md_text,
                mimetype="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''月次サマリー_{year}年{month:02d}月.md",
                },
            )

    @app.route("/api/monthly-report/<int:year>/<int:month>")
    def api_monthly_report(year, month):
        """月次レポートデータを返す"""
        if month < 1 or month > 12:
            return jsonify({"error": "month must be 1-12"}), 400
        report = get_monthly_report(year, month)
        return jsonify(report)

    # --- ローカル移行 API ---
    @app.route("/api/migration/export")
    def api_migration_export():
        """ローカル移行用の zip を生成してダウンロードする"""
        import shutil
        import tempfile

        from .migration import create_migration_archive

        temp_dir = tempfile.mkdtemp(prefix="timereaper-migration-export-")
        archive_name = f"timereaper_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        archive_path = create_migration_archive(
            output_path=os.path.join(temp_dir, archive_name),
            include_config=True,
        )

        @after_this_request
        def cleanup(response):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return response

        return send_file(
            archive_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=os.path.basename(archive_path),
        )

    @app.route("/api/migration/import", methods=["POST"])
    def api_migration_import():
        """ローカル移行 zip を取り込み、現在環境へ復元する"""
        import tempfile

        from .migration import import_migration_archive

        uploaded = request.files.get("file")
        if uploaded is None or uploaded.filename == "":
            return jsonify({"ok": False, "error": "zip ファイルを選択してください"}), 400

        filename = uploaded.filename or ""
        if not filename.lower().endswith(".zip"):
            return jsonify({"ok": False, "error": "zip ファイルのみ取り込めます"}), 400

        fd, temp_path = tempfile.mkstemp(prefix="timereaper-migration-import-", suffix=".zip")
        os.close(fd)
        try:
            uploaded.save(temp_path)
            result = import_migration_archive(
                archive_path=temp_path,
                restore_config=True,
                create_backup=True,
            )
            return jsonify({
                "ok": True,
                "message": "データのインポートが完了しました",
                "backup_path": result.get("backup_path"),
                "restored_count": result.get("restored_count", 0),
                "warnings": result.get("warnings", []),
                "restart_recommended": True,
            })
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except Exception as e:
            return jsonify({"ok": False, "error": f"インポートに失敗しました: {e}"}), 500
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    # --- アップデート API ---
    @app.route("/api/check-update")
    def api_check_update():
        """最新バージョンを確認する"""
        from .updater import check_for_updates
        info = check_for_updates()
        if info is None:
            return jsonify({"error": "アップデート情報を取得できませんでした"}), 503
        return jsonify({
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "is_update_available": info.is_update_available,
            "release_url": info.release_url,
            "release_notes": info.release_notes,
            "download_url": info.download_url,
            "published_at": info.published_at,
        })

    @app.route("/api/update", methods=["POST"])
    def api_perform_update():
        """アップデートを実行する（環境に応じて git pull か DMG ダウンロードを使い分ける）"""
        from .updater import perform_git_update, perform_dmg_update

        data = request.get_json() or {}
        download_url = data.get("download_url", "")

        # .app バンドルかどうかを判定
        app_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        is_app_bundle = app_path.endswith(".app/Contents/Resources") or \
                        ".app/" in app_path

        if is_app_bundle:
            # .app バンドル → DMG ダウンロードで更新
            if not download_url:
                # download_url が未取得の場合、再度チェックして取得を試みる
                from .updater import check_for_updates, GITHUB_OWNER, GITHUB_REPO
                info = check_for_updates()
                if info and info.download_url:
                    download_url = info.download_url
                elif info and info.is_update_available:
                    # API からアセット URL が取れない場合、既知のパターンで構築
                    tag = f"v{info.latest_version}"
                    download_url = (
                        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
                        f"/releases/download/{tag}/TimeReaper-{tag}.dmg"
                    )

            if not download_url:
                # download_url が構築できない場合（バージョン情報すら取れない）
                # RC タグパターンも試す
                from .updater import check_for_updates, GITHUB_OWNER, GITHUB_REPO
                info = check_for_updates() if 'info' not in dir() else info
                if info and info.latest_version:
                    tag = f"v{info.latest_version}"
                    for suffix in ["", "-rc"]:
                        candidate = (
                            f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
                            f"/releases/download/{tag}{suffix}/TimeReaper-{tag}{suffix}.dmg"
                        )
                        try:
                            head_resp = requests.head(candidate, timeout=5, allow_redirects=True)
                            if head_resp.status_code == 200:
                                download_url = candidate
                                break
                        except Exception:
                            continue

            if download_url:
                result = perform_dmg_update(download_url)
                if result.get("restart"):
                    # 成功時: アプリ終了をスケジュール
                    import threading
                    def _quit_later():
                        import time
                        time.sleep(1)
                        os._exit(0)
                    threading.Thread(target=_quit_later, daemon=True).start()
            else:
                result = {
                    "success": False,
                    "message": "DMG のダウンロード URL を特定できませんでした",
                    "details": "ネットワーク接続を確認し、再度お試しください。",
                }
        else:
            # 開発環境 → git pull
            result = perform_git_update()

        status_code = 200 if result["success"] else 500
        return jsonify(result), status_code

    @app.route("/api/version")
    def api_version():
        """現在のバージョン情報を返す"""
        from timereaper import __version__
        return jsonify({"version": __version__})

    # --- 設定ページ ---
    @app.route("/settings")
    def settings_page():
        """ユーザー設定ページ"""
        return render_template("settings.html")

    # --- 設定API ---
    @app.route("/api/settings", methods=["GET"])
    def api_get_settings():
        """ユーザー設定を取得する"""
        from .user_settings import get_user_settings
        settings = get_user_settings()
        return jsonify(settings)

    @app.route("/api/settings", methods=["POST"])
    def api_save_settings():
        """ユーザー設定を保存する"""
        data = request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "No data"}), 400
        from .user_settings import save_user_settings
        save_user_settings(data)
        # メニューバーアプリに設定変更を通知
        _notify_settings_changed(data)
        return jsonify({"ok": True})

    # --- ポモドーロAPI ---
    @app.route("/api/pomodoro/status")
    def api_pomodoro_status():
        """ポモドーロタイマーの現在の状態を返す"""
        timer = _get_pomodoro_timer()
        if timer is None:
            return jsonify({"state": "idle", "remaining_seconds": 0,
                            "total_seconds": 0, "session_count": 0,
                            "is_running": False, "remaining_display": "00:00"})
        return jsonify(timer.status.to_dict())

    @app.route("/api/pomodoro/<action>", methods=["POST"])
    def api_pomodoro_action(action):
        """ポモドーロタイマーのアクション（start_work, start_break, pause, resume, stop, skip）"""
        timer = _get_pomodoro_timer()
        if timer is None:
            return jsonify({"error": "Pomodoro timer not initialized"}), 503
        actions = {
            "start_work": timer.start_work,
            "start_break": timer.start_break,
            "pause": timer.pause,
            "resume": timer.resume,
            "stop": timer.stop,
            "skip": timer.skip,
        }
        fn = actions.get(action)
        if fn is None:
            return jsonify({"error": f"Unknown action: {action}"}), 400
        status = fn()
        return jsonify(status.to_dict())

    @app.route("/api/llm-classify", methods=["POST"])
    def api_llm_classify():
        """LLM でアクティビティを自動分類する"""
        data = request.get_json() or {}
        target_date = data.get("date", date.today().isoformat())
        dry_run = data.get("dry_run", False)
        min_confidence = data.get("min_confidence", 0.5)

        from .llm_classifier import classify_with_llm
        result = classify_with_llm(
            target_date=target_date,
            dry_run=dry_run,
            min_confidence=min_confidence,
        )
        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code

    @app.route("/api/llm-status")
    def api_llm_status():
        """LLM 分類の有効/無効状態を返す"""
        from .llm_classifier import get_llm_config
        config = get_llm_config()
        return jsonify({
            "enabled": config["enabled"],
            "has_api_key": bool(config["api_key"]),
            "model": config["model"],
        })

    @app.route("/api/permissions")
    def api_permissions():
        """macOS 権限の状態を確認して返す"""
        import subprocess
        import platform
        permissions: list[dict[str, Any]] = []

        # 1. アクセシビリティ
        accessibility_granted = False
        try:
            from ApplicationServices import AXIsProcessTrusted
            accessibility_granted = AXIsProcessTrusted()
        except ImportError:
            pass

        # AXIsProcessTrusted() は再ビルド後に誤って False を返すことがあるため
        # 実際に Accessibility API を使った機能テストでフォールバック
        if not accessibility_granted:
            try:
                from ApplicationServices import (
                    AXUIElementCreateSystemWide,
                    AXUIElementCopyAttributeValue,
                )
                system_wide = AXUIElementCreateSystemWide()
                err, _ = AXUIElementCopyAttributeValue(
                    system_wide, "AXFocusedApplication", None
                )
                if err == 0:
                    accessibility_granted = True
            except Exception:
                pass

        # さらに AppleScript での簡易テストもフォールバック
        if not accessibility_granted:
            try:
                r = subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to get name of first application process whose frontmost is true'],
                    capture_output=True, timeout=5,
                )
                if r.returncode == 0:
                    accessibility_granted = True
            except Exception:
                pass
        permissions.append({
            "name": "アクセシビリティ",
            "description": "アクティブウィンドウの検出に必要です",
            "granted": accessibility_granted,
            "setting_path": "システム設定 → プライバシーとセキュリティ → アクセシビリティ",
        })

        # 2. オートメーション (System Events)
        automation_granted = False
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of first application process whose frontmost is true'],
                capture_output=True, timeout=5,
            )
            automation_granted = r.returncode == 0
        except Exception:
            pass
        permissions.append({
            "name": "オートメーション（System Events）",
            "description": "AppleScript 経由でウィンドウ情報を取得するために必要です",
            "granted": automation_granted,
            "setting_path": "システム設定 → プライバシーとセキュリティ → オートメーション",
        })

        # 3. 画面収録 (macOS 14+)
        macos_version = int(platform.mac_ver()[0].split(".")[0]) if platform.mac_ver()[0] else 0
        if macos_version >= 14:
            screen_recording_granted: bool | None = False
            try:
                from Quartz import CGPreflightScreenCaptureAccess
                screen_recording_granted = CGPreflightScreenCaptureAccess()
            except (ImportError, AttributeError):
                screen_recording_granted = None

            # CGPreflightScreenCaptureAccess は再ビルド後に誤って False を返すため
            # CGWindowListCopyWindowInfo で非システムアプリのウィンドウタイトルが
            # 取得できるかで機能テスト（画面収録が許可されていれば取得可能）
            if not screen_recording_granted:
                try:
                    from Quartz import (
                        CGWindowListCopyWindowInfo,
                        kCGWindowListOptionOnScreenOnly,
                        kCGNullWindowID,
                    )
                    _system_owners = {"Window Server", "SystemUIServer", "Dock", "Spotlight"}
                    _windows = CGWindowListCopyWindowInfo(
                        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
                    )
                    for _w in (_windows or []):
                        _owner = _w.get("kCGWindowOwnerName", "")
                        _name = _w.get("kCGWindowName", "")
                        _layer = _w.get("kCGWindowLayer", 0)
                        if _owner not in _system_owners and _name and _layer == 0:
                            screen_recording_granted = True
                            break
                except Exception:
                    pass

            permissions.append({
                "name": "画面収録",
                "description": "macOS 14 以降でウィンドウタイトルの取得に必要です",
                "granted": screen_recording_granted,
                "setting_path": "システム設定 → プライバシーとセキュリティ → 画面収録",
            })

        # 4. 通知
        # UserNotifications フレームワークを明示ロード＋ブロック署名登録で
        # UNUserNotificationCenter の権限状態を正確に取得
        notification_granted = None
        notification_can_request = False
        try:
            import threading as _threading
            import objc

            # UserNotifications フレームワークを明示的にロード
            objc.loadBundle(
                'UserNotifications',
                bundle_path='/System/Library/Frameworks/UserNotifications.framework',
                module_globals={},
            )

            # getNotificationSettingsWithCompletionHandler: のブロック署名を登録
            objc.registerMetaDataForSelector(
                b'UNUserNotificationCenter',
                b'getNotificationSettingsWithCompletionHandler:',
                {
                    'arguments': {
                        2: {
                            'callable': {
                                'retval': {'type': b'v'},
                                'arguments': {
                                    0: {'type': b'^v'},
                                    1: {'type': b'@'},
                                },
                            }
                        }
                    }
                },
            )

            UNUserNotificationCenter = objc.lookUpClass("UNUserNotificationCenter")
            center = UNUserNotificationCenter.currentNotificationCenter()
            _event = _threading.Event()
            _result = [None]  # authorizationStatus の生値

            def _on_settings(settings):
                try:
                    _result[0] = settings.authorizationStatus()
                except Exception:
                    pass
                _event.set()

            center.getNotificationSettingsWithCompletionHandler_(_on_settings)
            from CoreFoundation import CFRunLoopRunInMode, kCFRunLoopDefaultMode
            import time as _time
            _start = _time.monotonic()
            while not _event.is_set() and (_time.monotonic() - _start) < 3.0:
                CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.1, False)

            auth_status = _result[0]
            if auth_status is not None:
                # 0=notDetermined, 1=denied, 2=authorized, 3=provisional
                if auth_status in (2, 3):
                    notification_granted = True
                elif auth_status == 1:
                    notification_granted = False
                else:
                    # notDetermined: UNUserNotificationCenter では未登録だが
                    # rumps は旧API（NSUserNotificationCenter）を使用するため
                    # そちらで通知が機能するかチェック
                    notification_granted = False
                    notification_can_request = True
        except Exception:
            pass

        # NSUserNotificationCenter（旧API）でのフォールバック確認
        # rumps が使う API なので、こちらが機能すれば通知は動作する
        if not notification_granted:
            try:
                import objc as _objc2
                NSUserNotificationCenter = _objc2.lookUpClass("NSUserNotificationCenter")
                _center = NSUserNotificationCenter.defaultUserNotificationCenter()
                if _center is not None:
                    # センターにアクセスでき、過去に通知配信歴があれば許可済みとみなす
                    _delivered = _center.deliveredNotifications()
                    if _delivered and len(_delivered) > 0:
                        notification_granted = True
                        notification_can_request = False
            except Exception:
                pass

        perm_entry = {
            "name": "通知",
            "description": "アップデート通知やポモドーロ通知に使用します",
            "granted": notification_granted,
            "setting_path": "システム設定 → 通知 → TimeReaper",
        }
        if notification_can_request:
            perm_entry["can_request"] = True
        permissions.append(perm_entry)

        return jsonify({"permissions": permissions})

    @app.route("/api/request-notification-permission", methods=["POST"])
    def request_notification_permission():
        """テスト通知を送信して通知機能を有効化する

        rumps は NSUserNotificationCenter（旧API）を使用しているため、
        UNUserNotificationCenter.requestAuthorization は未署名アプリでは失敗する。
        代わりに NSUserNotificationCenter でテスト通知を送信し、
        macOS の通知許可ダイアログを表示させる。
        """
        try:
            import objc
            NSUserNotificationCenter = objc.lookUpClass("NSUserNotificationCenter")
            NSUserNotification = objc.lookUpClass("NSUserNotification")

            center = NSUserNotificationCenter.defaultUserNotificationCenter()
            notification = NSUserNotification.alloc().init()
            notification.setTitle_("TimeReaper")
            notification.setSubtitle_("通知テスト")
            notification.setInformativeText_("通知が正常に機能しています ✅")
            center.deliverNotification_(notification)

            return jsonify({
                "success": True,
                "granted": True,
                "message": "テスト通知を送信しました。通知が表示されれば許可されています。",
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    return app


def run_dashboard():
    """ダッシュボードサーバーを起動する"""
    cfg = get_config()
    dashboard_cfg = cfg.get("dashboard", {})
    host = dashboard_cfg.get("host", "127.0.0.1")
    port = dashboard_cfg.get("port", 5555)

    app = create_app()
    app.run(host=host, port=port, debug=False, use_reloader=False)
