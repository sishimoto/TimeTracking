"""
Webダッシュボード - Flask API
アクティビティデータを可視化するためのREST APIとダッシュボードを提供します。
"""

import os
from datetime import date, timedelta
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS

from .config import get_config
from .database import (
    get_activities,
    get_daily_summary,
    get_timeline,
    get_hourly_breakdown,
    get_project_summary,
    get_calendar_events,
    get_weekly_trend,
    update_activity_tags,
    update_activity_tags_by_time,
    get_time_blocks,
)


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

    return app


def run_dashboard():
    """ダッシュボードサーバーを起動する"""
    cfg = get_config()
    dashboard_cfg = cfg.get("dashboard", {})
    host = dashboard_cfg.get("host", "127.0.0.1")
    port = dashboard_cfg.get("port", 5555)

    app = create_app()
    app.run(host=host, port=port, debug=False, use_reloader=False)
