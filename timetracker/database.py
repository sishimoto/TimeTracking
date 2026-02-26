"""
データベース層
SQLiteを使ったアクティビティログの保存・検索を行います。
"""

import sqlite3
import os
from datetime import datetime, date, timedelta
from typing import Optional
from contextlib import contextmanager

from .config import get_config, ensure_data_dir


def get_db_path() -> str:
    cfg = get_config()
    return cfg["database"]["path"]


def init_db():
    """データベースとテーブルを初期化する"""
    ensure_data_dir()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # アクティビティログ - メインテーブル
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            app_name TEXT,
            window_title TEXT,
            bundle_id TEXT,
            url TEXT,
            duration_seconds REAL DEFAULT 0,
            is_idle INTEGER DEFAULT 0,
            project TEXT,
            work_phase TEXT,
            category TEXT,
            notes TEXT
        )
    """)

    # カレンダーイベント
    c.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            title TEXT,
            description TEXT,
            start_time TEXT,
            end_time TEXT,
            attendees TEXT,
            location TEXT,
            calendar_id TEXT,
            synced_at TEXT
        )
    """)

    # Slackアクティビティ
    c.execute("""
        CREATE TABLE IF NOT EXISTS slack_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            channel_name TEXT,
            channel_id TEXT,
            workspace TEXT,
            is_active INTEGER DEFAULT 0,
            conversation_with TEXT
        )
    """)

    # 手動プロジェクトタグ（ユーザーが手動で期間にプロジェクトを割り当て）
    c.execute("""
        CREATE TABLE IF NOT EXISTS manual_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            project TEXT,
            work_phase TEXT,
            notes TEXT
        )
    """)

    # 日次サマリー（集計キャッシュ）
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            app_name TEXT,
            project TEXT,
            work_phase TEXT,
            total_seconds REAL DEFAULT 0,
            UNIQUE(date, app_name, project, work_phase)
        )
    """)

    # インデックス
    c.execute("CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_log(timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_activity_app ON activity_log(app_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_activity_project ON activity_log(project)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_calendar_start ON calendar_events(start_time)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_summary(date)")

    conn.commit()
    conn.close()


@contextmanager
def get_connection():
    """データベース接続のコンテキストマネージャ"""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_activity(
    app_name: str,
    window_title: str,
    bundle_id: str = "",
    url: str = "",
    duration_seconds: float = 0,
    is_idle: bool = False,
    project: str = "",
    work_phase: str = "",
    category: str = "",
    timestamp: Optional[str] = None,
):
    """アクティビティログを1件挿入する"""
    ts = timestamp or datetime.now().isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO activity_log
            (timestamp, app_name, window_title, bundle_id, url,
             duration_seconds, is_idle, project, work_phase, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, app_name, window_title, bundle_id, url,
             duration_seconds, int(is_idle), project, work_phase, category),
        )


def get_activities(
    start: Optional[str] = None,
    end: Optional[str] = None,
    app_name: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 1000,
) -> list[dict]:
    """アクティビティログを検索する"""
    query = "SELECT * FROM activity_log WHERE 1=1"
    params = []
    if start:
        query += " AND timestamp >= ?"
        params.append(start)
    if end:
        query += " AND timestamp <= ?"
        params.append(end)
    if app_name:
        query += " AND app_name = ?"
        params.append(app_name)
    if project:
        query += " AND project = ?"
        params.append(project)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_daily_summary(target_date: Optional[str] = None) -> list[dict]:
    """日次サマリーを取得する"""
    if target_date is None:
        target_date = date.today().isoformat()

    with get_connection() as conn:
        # リアルタイム集計
        rows = conn.execute(
            """SELECT
                app_name,
                project,
                work_phase,
                SUM(duration_seconds) as total_seconds,
                COUNT(*) as record_count
            FROM activity_log
            WHERE date(timestamp) = ? AND is_idle = 0
            GROUP BY app_name, project, work_phase
            ORDER BY total_seconds DESC""",
            (target_date,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_timeline(target_date: Optional[str] = None) -> list[dict]:
    """タイムラインデータを取得する（時間帯ごとのアクティビティ）"""
    if target_date is None:
        target_date = date.today().isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                timestamp,
                app_name,
                window_title,
                url,
                duration_seconds,
                is_idle,
                project,
                work_phase,
                category
            FROM activity_log
            WHERE date(timestamp) = ?
            ORDER BY timestamp ASC""",
            (target_date,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_hourly_breakdown(target_date: Optional[str] = None) -> list[dict]:
    """時間帯ごとのアプリ使用サマリー"""
    if target_date is None:
        target_date = date.today().isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                strftime('%H', timestamp) as hour,
                app_name,
                work_phase,
                SUM(duration_seconds) as total_seconds
            FROM activity_log
            WHERE date(timestamp) = ? AND is_idle = 0
            GROUP BY hour, app_name, work_phase
            ORDER BY hour ASC, total_seconds DESC""",
            (target_date,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_project_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """プロジェクトごとの作業時間サマリー"""
    if start_date is None:
        start_date = (date.today() - timedelta(days=7)).isoformat()
    if end_date is None:
        end_date = date.today().isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                project,
                work_phase,
                SUM(duration_seconds) as total_seconds,
                COUNT(DISTINCT date(timestamp)) as active_days
            FROM activity_log
            WHERE date(timestamp) BETWEEN ? AND ?
              AND is_idle = 0
              AND project IS NOT NULL AND project != ''
            GROUP BY project, work_phase
            ORDER BY total_seconds DESC""",
            (start_date, end_date),
        ).fetchall()
        return [dict(row) for row in rows]


def insert_calendar_event(event_data: dict):
    """カレンダーイベントをupsertする"""
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO calendar_events
            (event_id, title, description, start_time, end_time,
             attendees, location, calendar_id, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_data.get("event_id", ""),
                event_data.get("title", ""),
                event_data.get("description", ""),
                event_data.get("start_time", ""),
                event_data.get("end_time", ""),
                event_data.get("attendees", ""),
                event_data.get("location", ""),
                event_data.get("calendar_id", ""),
                datetime.now().isoformat(),
            ),
        )


def get_calendar_events(target_date: Optional[str] = None) -> list[dict]:
    """指定日のカレンダーイベントを取得"""
    if target_date is None:
        target_date = date.today().isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM calendar_events
            WHERE date(start_time) = ?
            ORDER BY start_time ASC""",
            (target_date,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_weekly_trend(weeks: int = 4) -> list[dict]:
    """週ごとの作業傾向を取得"""
    start_date = (date.today() - timedelta(weeks=weeks)).isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                strftime('%Y-W%W', timestamp) as week,
                work_phase,
                SUM(duration_seconds) as total_seconds
            FROM activity_log
            WHERE date(timestamp) >= ? AND is_idle = 0
            GROUP BY week, work_phase
            ORDER BY week ASC""",
            (start_date,),
        ).fetchall()
        return [dict(row) for row in rows]
