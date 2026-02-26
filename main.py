"""
TimeTracker メインエントリーポイント
コマンドラインから起動するためのCLIインターフェースを提供します。
"""

import argparse
import logging
import sys
import os

# パスの設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetracker.config import load_config, get_config, ensure_data_dir
from timetracker.database import init_db


def setup_logging(verbose: bool = False):
    """ロギングの設定"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_start(args):
    """メニューバーアプリを起動してトラッキング開始"""
    from timetracker.menubar import run_menubar_app

    print("⏱ TimeTracker を起動しています...")
    print("  メニューバーに常駐します")
    print(f"  ダッシュボード: http://127.0.0.1:{get_config()['dashboard']['port']}")
    print()
    print("  終了するにはメニューバーのアイコンから「終了」を選択してください")

    run_menubar_app()


def cmd_dashboard(args):
    """ダッシュボードのみ起動"""
    from timetracker.dashboard import run_dashboard

    cfg = get_config()
    host = cfg["dashboard"]["host"]
    port = cfg["dashboard"]["port"]
    print(f"📊 ダッシュボード起動中: http://{host}:{port}")
    run_dashboard()


def cmd_monitor(args):
    """CLIモードでモニタリング（メニューバーなし）"""
    import time
    from timetracker.monitor import ActiveWindowMonitor
    from timetracker.classifier import ActivityClassifier
    from timetracker.database import insert_activity

    cfg = get_config()
    interval = cfg.get("monitor", {}).get("interval_seconds", 5)

    monitor = ActiveWindowMonitor(
        idle_threshold=cfg.get("monitor", {}).get("idle_threshold_seconds", 300)
    )
    classifier = ActivityClassifier()
    last_ts = 0.0

    print(f"⏱ CLIモニタリング開始（{interval}秒間隔）")
    print("  Ctrl+C で停止")
    print()

    try:
        while True:
            info = monitor.get_active_window()
            if info:
                now = time.time()
                duration = min(now - last_ts, interval * 2) if last_ts > 0 else 0
                classification = classifier.classify(info)

                insert_activity(
                    app_name=info.app_name,
                    window_title=info.window_title,
                    bundle_id=info.bundle_id,
                    url=info.url,
                    duration_seconds=duration,
                    is_idle=info.is_idle,
                    project=classification["project"],
                    work_phase=classification["work_phase"],
                    category=classification["category"],
                    timestamp=info.timestamp,
                )

                status = "💤" if info.is_idle else "📝"
                phase = classification["work_phase"] or "-"
                proj = classification["project"] or "-"
                print(
                    f"  {status} [{info.timestamp[11:19]}] "
                    f"{info.app_name:20s} | {phase:15s} | {proj:15s} | "
                    f"{info.window_title[:50]}"
                )

                last_ts = now

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n⏹ モニタリング停止")


def cmd_sync_calendar(args):
    """Google Calendarを手動同期"""
    from timetracker.integrations.google_calendar import GoogleCalendarSync

    sync = GoogleCalendarSync()
    if not sync.is_enabled:
        print("❌ Google Calendar連携が無効です。config.yamlで enabled: true に設定してください。")
        return

    print("📅 Google Calendar同期中...")
    events = sync.sync_events(days_ahead=args.days)
    print(f"✅ {len(events)} 件のイベントを同期しました")
    for evt in events:
        print(f"  - {evt['start_time'][:16]} {evt['title']}")
        if evt['attendees']:
            print(f"    参加者: {evt['attendees']}")


def cmd_export(args):
    """データをCSVエクスポート"""
    import csv
    from timetracker.database import get_activities

    activities = get_activities(start=args.start, end=args.end, limit=100000)
    output = args.output or f"timetracker_export_{args.start or 'all'}_{args.end or 'all'}.csv"

    with open(output, "w", newline="", encoding="utf-8") as f:
        if activities:
            writer = csv.DictWriter(f, fieldnames=activities[0].keys())
            writer.writeheader()
            writer.writerows(activities)

    print(f"✅ {len(activities)} 件のレコードを {output} にエクスポートしました")


def main():
    parser = argparse.ArgumentParser(
        description="TimeTracker - macOS稼働時間管理アプリ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python main.py start          # メニューバーアプリとして起動
  python main.py monitor        # CLIモードでモニタリング
  python main.py dashboard      # ダッシュボードのみ起動
  python main.py sync-calendar  # Google Calendar同期
  python main.py export --start 2025-01-01 --end 2025-01-31
        """,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログを表示")
    parser.add_argument(
        "-c", "--config", type=str, default=None, help="設定ファイルのパス"
    )

    subparsers = parser.add_subparsers(dest="command", help="コマンド")

    # start
    subparsers.add_parser("start", help="メニューバーアプリとして起動")

    # monitor
    subparsers.add_parser("monitor", help="CLIモードでモニタリング")

    # dashboard
    subparsers.add_parser("dashboard", help="ダッシュボードのみ起動")

    # sync-calendar
    cal_parser = subparsers.add_parser("sync-calendar", help="Google Calendar同期")
    cal_parser.add_argument(
        "--days", type=int, default=1, help="何日先まで取得するか"
    )

    # export
    exp_parser = subparsers.add_parser("export", help="CSVエクスポート")
    exp_parser.add_argument("--start", type=str, help="開始日 (YYYY-MM-DD)")
    exp_parser.add_argument("--end", type=str, help="終了日 (YYYY-MM-DD)")
    exp_parser.add_argument("--output", type=str, help="出力ファイル名")

    args = parser.parse_args()

    setup_logging(args.verbose)
    load_config(args.config)
    ensure_data_dir()
    init_db()

    commands = {
        "start": cmd_start,
        "monitor": cmd_monitor,
        "dashboard": cmd_dashboard,
        "sync-calendar": cmd_sync_calendar,
        "export": cmd_export,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
