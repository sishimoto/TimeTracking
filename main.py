"""
TimeReaper メインエントリーポイント
コマンドラインから起動するためのCLIインターフェースを提供します。
"""

import argparse
import logging
import sys
import os

# パスの設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timereaper.config import load_config, get_config, ensure_data_dir
from timereaper.database import init_db


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
    from timereaper.menubar import run_menubar_app

    print("⏱ TimeReaper を起動しています...")
    print("  メニューバーに常駐します")
    print(f"  ダッシュボード: http://127.0.0.1:{get_config()['dashboard']['port']}")
    print()
    print("  終了するにはメニューバーのアイコンから「終了」を選択してください")

    run_menubar_app()


def cmd_dashboard(args):
    """ダッシュボードのみ起動"""
    from timereaper.dashboard import run_dashboard

    cfg = get_config()
    host = cfg["dashboard"]["host"]
    port = cfg["dashboard"]["port"]
    print(f"📊 ダッシュボード起動中: http://{host}:{port}")
    run_dashboard()


def cmd_monitor(args):
    """CLIモードでモニタリング（メニューバーなし）"""
    import time
    from timereaper.monitor import ActiveWindowMonitor
    from timereaper.classifier import ActivityClassifier
    from timereaper.database import insert_activity
    from timereaper.integrations.mac_calendar import get_current_meeting

    cfg = get_config()
    interval = cfg.get("monitor", {}).get("interval_seconds", 5)

    monitor = ActiveWindowMonitor(
        idle_threshold=cfg.get("monitor", {}).get("idle_threshold_seconds", 300)
    )
    classifier = ActivityClassifier()
    last_ts = 0.0
    was_idle = False

    print(f"⏱ CLIモニタリング開始（{interval}秒間隔）")
    print(f"  アイドル閾値: {cfg.get('monitor', {}).get('idle_threshold_seconds', 300)}秒")
    print("  Ctrl+C で停止")
    print()

    try:
        while True:
            info = monitor.get_active_window()
            if info:
                now = time.time()

                if info.is_idle:
                    # アイドル状態 → 記録スキップ（計測一時停止）
                    if not was_idle:
                        print(f"  💤 [{info.timestamp[11:19]}] アイドル検出 - 計測を一時停止")
                        was_idle = True
                else:
                    # アクティブ状態
                    if was_idle:
                        # アイドルから復帰 → タイムスタンプをリセット
                        print(f"  ▶️  [{info.timestamp[11:19]}] アイドル復帰 - 計測を再開")
                        was_idle = False
                        last_ts = now  # アイドル期間を含めない

                    duration = min(now - last_ts, interval * 2) if last_ts > 0 else 0

                    # カレンダー会議情報を取得
                    current_meeting = get_current_meeting()
                    meeting_title = current_meeting.get("title", "") if current_meeting else ""

                    # カレンダーイベントの種類を判定
                    cal_type = classifier.classify_calendar_event(meeting_title) if current_meeting else None

                    classification = classifier.classify(info, meeting_title=meeting_title)

                    # カレンダーイベント種別に応じた上書き
                    if cal_type == "meeting":
                        classification["work_phase"] = "meeting"
                    elif cal_type == "other":
                        classification["project"] = "その他"
                        classification["work_phase"] = "other"

                    # アクティブ時のみ記録
                    insert_activity(
                        app_name=info.app_name,
                        window_title=info.window_title,
                        bundle_id=info.bundle_id,
                        url=info.url,
                        tab_title=info.tab_title,
                        duration_seconds=duration,
                        is_idle=False,
                        project=classification["project"],
                        work_phase=classification["work_phase"],
                        category=classification["category"],
                        timestamp=info.timestamp,
                    )

                    phase = classification["work_phase"] or "-"
                    proj = classification["project"] or "-"
                    tab_info = f" | tab: {info.tab_title[:30]}" if info.tab_title else ""
                    print(
                        f"  📝 [{info.timestamp[11:19]}] "
                        f"{info.app_name:20s} | {phase:15s} | {proj:15s} | "
                        f"{info.window_title[:50]}{tab_info}"
                    )

                    last_ts = now

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n⏹ モニタリング停止")


def cmd_sync_calendar(args):
    """カレンダーを同期（Mac Calendar 優先、Google Calendar フォールバック）"""
    cfg = get_config()

    # Mac Calendar を優先
    mac_cal_config = cfg.get("mac_calendar", {})
    if mac_cal_config.get("enabled", False):
        from timereaper.integrations.mac_calendar import MacCalendarSync

        sync = MacCalendarSync()

        # --list-calendars オプション
        if getattr(args, "list_calendars", False):
            calendars = sync.list_calendars_detailed()
            if calendars:
                print("📅 利用可能なカレンダー:")
                for cal in calendars:
                    source = cal.get("source", "")
                    title = cal.get("title", "")
                    print(f"  - {title}  (ソース: {source})")
            else:
                print("❌ カレンダーにアクセスできません。システム設定で許可してください。")
            return

        print("📅 Mac Calendar 同期中...")
        events = sync.sync_events(days_ahead=args.days)
        print(f"✅ {len(events)} 件のイベントを同期しました")
        for evt in events:
            print(f"  - {evt['start_time'][:16]} {evt['title']}")
            if evt["attendees"]:
                print(f"    参加者: {evt['attendees']}")
            if evt["location"]:
                print(f"    場所: {evt['location']}")
        return

    # Google Calendar フォールバック
    gc_config = cfg.get("google_calendar", {})
    if gc_config.get("enabled", False):
        from timereaper.integrations.google_calendar import GoogleCalendarSync

        sync = GoogleCalendarSync()
        print("📅 Google Calendar 同期中...")
        events = sync.sync_events(days_ahead=args.days)
        print(f"✅ {len(events)} 件のイベントを同期しました")
        for evt in events:
            print(f"  - {evt['start_time'][:16]} {evt['title']}")
            if evt["attendees"]:
                print(f"    参加者: {evt['attendees']}")
        return

    print("❌ カレンダー連携が無効です。config.yaml で mac_calendar.enabled: true に設定してください。")


def cmd_export(args):
    """データをCSVエクスポート"""
    import csv
    from timereaper.database import get_activities

    activities = get_activities(start=args.start, end=args.end, limit=100000)
    output = args.output or f"timereaper_export_{args.start or 'all'}_{args.end or 'all'}.csv"

    with open(output, "w", newline="", encoding="utf-8") as f:
        if activities:
            writer = csv.DictWriter(f, fieldnames=activities[0].keys())
            writer.writeheader()
            writer.writerows(activities)

    print(f"✅ {len(activities)} 件のレコードを {output} にエクスポートしました")


def cmd_cleanup(args):
    """データベースの重複レコードを削除"""
    from timereaper.database import deduplicate_activity_log

    # まず重複数を確認
    count = deduplicate_activity_log(dry_run=True)
    if count == 0:
        print("✅ 重複レコードはありません")
        return

    print(f"🔍 {count} 件の重複レコードが見つかりました")

    if args.dry_run:
        print("  --execute オプションで実際に削除できます")
        return

    # 実際に削除
    deleted = deduplicate_activity_log(dry_run=False)
    print(f"🗑️ {deleted} 件の重複レコードを削除しました")


def main():
    parser = argparse.ArgumentParser(
        description="TimeReaper - macOS稼働時間管理アプリ",
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
    cal_parser = subparsers.add_parser("sync-calendar", help="カレンダー同期")
    cal_parser.add_argument(
        "--days", type=int, default=1, help="何日先まで取得するか"
    )
    cal_parser.add_argument(
        "--list-calendars", action="store_true", help="利用可能なカレンダー一覧を表示"
    )

    # export
    exp_parser = subparsers.add_parser("export", help="CSVエクスポート")
    exp_parser.add_argument("--start", type=str, help="開始日 (YYYY-MM-DD)")
    exp_parser.add_argument("--end", type=str, help="終了日 (YYYY-MM-DD)")
    exp_parser.add_argument("--output", type=str, help="出力ファイル名")

    # cleanup
    cleanup_parser = subparsers.add_parser("cleanup", help="重複レコードを削除")
    cleanup_parser.add_argument(
        "--execute", action="store_true", dest="execute",
        help="実際に削除を実行（デフォルトはドライラン）"
    )
    cleanup_parser.set_defaults(dry_run=True)

    args = parser.parse_args()

    # --execute が指定された場合 dry_run を無効に
    if hasattr(args, 'execute') and args.execute:
        args.dry_run = False

    # .app バンドルからの起動等、サブコマンド未指定時はデフォルトで start
    if args.command is None:
        args.command = "start"

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
        "cleanup": cmd_cleanup,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
