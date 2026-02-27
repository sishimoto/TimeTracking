#!/bin/bash
# TimeTracker 起動スクリプト
# ダブルクリックまたはターミナルから実行できます

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 既存プロセスを停止
pkill -f "python main.py start" 2>/dev/null
lsof -ti:5555 | xargs kill -9 2>/dev/null
sleep 1

# 仮想環境を有効化して起動
source venv/bin/activate
python main.py start &

echo "⏱ TimeTracker を起動しました"
echo "   ダッシュボード: http://127.0.0.1:5555"
echo "   停止するには: pkill -f 'python main.py start'"
