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

    return app


def run_dashboard():
    """ダッシュボードサーバーを起動する"""
    cfg = get_config()
    dashboard_cfg = cfg.get("dashboard", {})
    host = dashboard_cfg.get("host", "127.0.0.1")
    port = dashboard_cfg.get("port", 5555)

    app = create_app()
    app.run(host=host, port=port, debug=False, use_reloader=False)
