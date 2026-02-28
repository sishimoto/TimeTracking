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
            tab_title TEXT,
            duration_seconds REAL DEFAULT 0,
            is_idle INTEGER DEFAULT 0,
            project TEXT,
            work_phase TEXT,
            category TEXT,
            notes TEXT
        )
    """)

    # 既存テーブルに tab_title カラムがない場合は追加
    try:
        c.execute("ALTER TABLE activity_log ADD COLUMN tab_title TEXT")
    except sqlite3.OperationalError:
        pass  # 既に存在する

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
            is_all_day INTEGER DEFAULT 0,
            synced_at TEXT
        )
    """)

    # 既存テーブルに is_all_day カラムがない場合は追加
    try:
        c.execute("ALTER TABLE calendar_events ADD COLUMN is_all_day INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 既に存在する

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
    tab_title: str = "",
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
            (timestamp, app_name, window_title, bundle_id, url, tab_title,
             duration_seconds, is_idle, project, work_phase, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, app_name, window_title, bundle_id, url, tab_title,
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
                tab_title,
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
             attendees, location, calendar_id, is_all_day, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_data.get("event_id", ""),
                event_data.get("title", ""),
                event_data.get("description", ""),
                event_data.get("start_time", ""),
                event_data.get("end_time", ""),
                event_data.get("attendees", ""),
                event_data.get("location", ""),
                event_data.get("calendar_id", ""),
                int(event_data.get("is_all_day", False)),
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


def get_current_meeting() -> Optional[dict]:
    """現在進行中の会議を取得する（終日イベントを除く）"""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM calendar_events
            WHERE start_time <= ? AND end_time >= ?
              AND (is_all_day = 0 OR is_all_day IS NULL)
            ORDER BY start_time DESC LIMIT 1""",
            (now, now),
        ).fetchone()
        return dict(row) if row else None


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


def update_activity_tags(
    start_time: str,
    end_time: str,
    app_name: str,
    work_phase: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """指定期間・アプリのアクティビティログの work_phase と project を一括更新する"""
    updates = []
    params = []
    if work_phase is not None:
        updates.append("work_phase = ?")
        params.append(work_phase)
    if project is not None:
        updates.append("project = ?")
        params.append(project)
    if not updates:
        return 0

    params.extend([start_time, end_time, app_name])

    with get_connection() as conn:
        cursor = conn.execute(
            f"""UPDATE activity_log
            SET {', '.join(updates)}
            WHERE timestamp >= ? AND timestamp <= ? AND app_name = ?""",
            params,
        )
        return cursor.rowcount


def update_activity_tags_by_time(
    start_time: str,
    end_time: str,
    work_phase: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    """指定期間の全アクティビティログの work_phase と project を一括更新する（アプリ不問）"""
    updates = []
    params = []
    if work_phase is not None:
        updates.append("work_phase = ?")
        params.append(work_phase)
    if project is not None:
        updates.append("project = ?")
        params.append(project)
    if not updates:
        return 0

    params.extend([start_time, end_time])

    with get_connection() as conn:
        cursor = conn.execute(
            f"""UPDATE activity_log
            SET {', '.join(updates)}
            WHERE timestamp >= ? AND timestamp < ? AND is_idle = 0""",
            params,
        )
        return cursor.rowcount


def get_time_blocks(target_date: Optional[str] = None, block_minutes: int = 10) -> list[dict]:
    """指定日のアクティビティを N 分ブロックにまとめたサマリーを返す"""
    if target_date is None:
        target_date = date.today().isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                timestamp, app_name, window_title, tab_title,
                duration_seconds, work_phase, project, category
            FROM activity_log
            WHERE date(timestamp) = ? AND is_idle = 0
            ORDER BY timestamp ASC""",
            (target_date,),
        ).fetchall()

    blocks = []
    for row in rows:
        r = dict(row)
        ts = r["timestamp"]
        # HH:MM からブロック開始時刻を決定
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            continue
        block_start_min = (dt.hour * 60 + dt.minute) // block_minutes * block_minutes
        block_h, block_m = divmod(block_start_min, 60)
        block_key = f"{block_h:02d}:{block_m:02d}"
        block_start = f"{target_date}T{block_key}:00"
        block_end_min = block_start_min + block_minutes
        be_h, be_m = divmod(block_end_min, 60)
        block_end = f"{target_date}T{be_h:02d}:{be_m:02d}:00"

        # タイトル情報
        tab = r["tab_title"] or ""
        win = r["window_title"] or ""
        title_text = tab if tab else win

        # 既存ブロックに追加 or 新規ブロック
        if blocks and blocks[-1]["block_start"] == block_start:
            blk = blocks[-1]
            blk["total_seconds"] += r["duration_seconds"] or 0
            blk["record_count"] += 1
            # アプリ集計
            app = r["app_name"] or ""
            blk["apps"][app] = blk["apps"].get(app, 0) + (r["duration_seconds"] or 0)
            # work_phase / project の多数決用カウント
            wp = r["work_phase"] or ""
            blk["_wp_counts"][wp] = blk["_wp_counts"].get(wp, 0) + (r["duration_seconds"] or 0)
            pj = r["project"] or ""
            blk["_pj_counts"][pj] = blk["_pj_counts"].get(pj, 0) + (r["duration_seconds"] or 0)
            # タイトル収集（ユニーク、最大5件）
            if title_text and title_text not in blk["_titles_set"]:
                blk["_titles_set"].add(title_text)
                blk["_titles"].append(title_text)
        else:
            app = r["app_name"] or ""
            wp = r["work_phase"] or ""
            pj = r["project"] or ""
            titles_set = set()
            titles_list = []
            if title_text:
                titles_set.add(title_text)
                titles_list.append(title_text)
            blocks.append({
                "block_start": block_start,
                "block_end": block_end,
                "block_label": block_key,
                "total_seconds": r["duration_seconds"] or 0,
                "record_count": 1,
                "apps": {app: r["duration_seconds"] or 0},
                "_wp_counts": {wp: r["duration_seconds"] or 0},
                "_pj_counts": {pj: r["duration_seconds"] or 0},
                "_titles_set": titles_set,
                "_titles": titles_list,
            })

    # 多数決で work_phase / project を決定し、内部カウントを除去
    for blk in blocks:
        wp_counts = blk.pop("_wp_counts")
        pj_counts = blk.pop("_pj_counts")
        blk["work_phase"] = max(wp_counts, key=wp_counts.get) if wp_counts else ""
        blk["project"] = max(pj_counts, key=pj_counts.get) if pj_counts else ""
        # アプリを秒数順にソートしてリスト化
        sorted_apps = sorted(blk["apps"].items(), key=lambda x: -x[1])
        blk["top_apps"] = [{"app": a, "seconds": s} for a, s in sorted_apps[:3]]
        del blk["apps"]
        # タイトル一覧（最大5件）
        blk["titles"] = blk.pop("_titles")[:5]
        blk.pop("_titles_set", None)

    return blocks
