"""
Webダッシュボード - Flask API
アクティビティデータを可視化するためのREST APIとダッシュボードを提供します。
"""

import os
from datetime import date, timedelta
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS
import requests

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

    return app


def run_dashboard():
    """ダッシュボードサーバーを起動する"""
    cfg = get_config()
    dashboard_cfg = cfg.get("dashboard", {})
    host = dashboard_cfg.get("host", "127.0.0.1")
    port = dashboard_cfg.get("port", 5555)

    app = create_app()
    app.run(host=host, port=port, debug=False, use_reloader=False)
