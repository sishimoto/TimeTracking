"""
LLM ベースのアクティビティ自動分類
OpenAI API を使用して、未分類のアクティビティを一括で分類する。

使い方:
  1. config.yaml に llm セクションを追加:
     llm:
       enabled: true
       api_key: "sk-..."          # または環境変数 OPENAI_API_KEY
       model: "gpt-4o-mini"       # コスト効率の良いモデル推奨
       batch_size: 20             # 1回のAPI呼び出しで処理する件数
       max_daily_calls: 50        # 1日あたりのAPI呼び出し上限

  2. ダッシュボードまたは CLI から実行:
     python -m timereaper.llm_classifier --date 2026-03-03
"""

import json
import logging
import os
import re
import sqlite3
from datetime import date, datetime
from typing import Optional

from .config import get_config
from .database import get_db_path

logger = logging.getLogger(__name__)


def get_llm_config() -> dict:
    """LLM 設定を取得する"""
    cfg = get_config()
    llm_cfg = cfg.get("llm", {})
    return {
        "enabled": llm_cfg.get("enabled", False),
        "api_key": llm_cfg.get("api_key", "") or os.environ.get("OPENAI_API_KEY", ""),
        "model": llm_cfg.get("model", "gpt-4o-mini"),
        "batch_size": llm_cfg.get("batch_size", 20),
        "max_daily_calls": llm_cfg.get("max_daily_calls", 50),
    }


def get_available_categories() -> dict:
    """config.yaml からタグカテゴリを取得"""
    cfg = get_config()
    rules = cfg.get("classification_rules", {})
    return {
        "task_categories": rules.get("task_categories", []),
        "cost_categories": rules.get("cost_categories", []),
    }


def get_unclassified_activities(target_date: str, limit: int = 100) -> list[dict]:
    """未分類または汎用分類のアクティビティを取得する
    
    「未分類」の定義:
    - work_phase が空、またはプロジェクトタイプのみ（サブフェーズなし）
    - 同一アプリ+タイトルの組み合わせを重複除去
    """
    db_path = get_db_path()
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT 
                app_name, 
                window_title, 
                tab_title,
                url, 
                work_phase, 
                project,
                COUNT(*) as count,
                SUM(duration_seconds) as total_duration
            FROM activity_log
            WHERE date(timestamp) = ?
              AND is_idle = 0
            GROUP BY app_name, 
                     COALESCE(NULLIF(tab_title, ''), window_title),
                     work_phase, project
            ORDER BY total_duration DESC
            LIMIT ?
        """, (target_date, limit))
        
        return [dict(row) for row in cursor.fetchall()]


def build_classification_prompt(
    activities: list[dict],
    task_categories: list[str],
    cost_categories: list[str],
) -> str:
    """LLM に送る分類プロンプトを構築する"""
    
    # アクティビティリストを構造化
    activity_lines = []
    for i, act in enumerate(activities):
        title = act.get("tab_title") or act.get("window_title", "")
        line = (
            f"{i+1}. app={act['app_name']}, "
            f"title=\"{title[:100]}\", "
            f"url=\"{(act.get('url') or '')[:100]}\", "
            f"current_task=\"{act.get('work_phase', '')}\", "
            f"current_cost=\"{act.get('project', '')}\", "
            f"duration={act.get('total_duration', 0)}s"
        )
        activity_lines.append(line)
    
    activities_text = "\n".join(activity_lines)
    
    prompt = f"""あなたはエンジニアの作業内容を分類するアシスタントです。
以下のアクティビティログを分析し、各エントリに最適な「タスク分類」と「費用分類」を割り当ててください。

## 分類ルール

### タスク分類 (work_phase)
以下から選択してください:
{json.dumps(task_categories, ensure_ascii=False, indent=2)}

### 費用分類 (project)  
以下から選択してください:
{json.dumps(cost_categories, ensure_ascii=False, indent=2)}

## 判定のガイドライン
- アプリ名、ウィンドウタイトル、URLを総合的に判断する
- IDE（VS Code, Cursor等）で特定プロジェクトのファイルを開いている場合、プロジェクト名からカスタム開発/プロダクト開発を判定
- ブラウザでGitHub/Jira等を開いている場合、URLからプロジェクトを推定
- Zoom/Google Meet/Slack通話はmeetingに分類
- 判断できない場合は current_task/current_cost を維持
- 各エントリのdurationが大きいほど重要（長時間使用している）

## アクティビティログ
{activities_text}

## 出力形式
JSON配列で返してください。各要素は以下の形式:
```json
[
  {{"index": 1, "work_phase": "カスタム開発-実装", "project": "Impulse個別開発", "confidence": 0.8}},
  ...
]
```
- index: アクティビティの番号（1始まり）
- work_phase: タスク分類
- project: 費用分類（独立カテゴリの場合は空文字列）
- confidence: 確信度（0.0〜1.0）。0.5未満の場合は元の分類を維持します
"""
    return prompt


def call_openai_api(prompt: str, config: dict) -> Optional[list[dict]]:
    """OpenAI API を呼び出して分類結果を取得する"""
    api_key = config["api_key"]
    model = config["model"]
    
    if not api_key:
        logger.error("OpenAI API キーが設定されていません")
        return None
    
    try:
        import requests
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a classification assistant. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        
        if response.status_code != 200:
            logger.error(f"OpenAI API エラー: HTTP {response.status_code}: {response.text}")
            return None
        
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        # JSON パース
        parsed = json.loads(content)
        
        # レスポンスが {"classifications": [...]} の形式の場合
        if isinstance(parsed, dict):
            for key in ("classifications", "results", "data"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            # 辞書の最初のリスト値を探す
            for v in parsed.values():
                if isinstance(v, list):
                    return v
        elif isinstance(parsed, list):
            return parsed
        
        logger.warning(f"予期しないレスポンス形式: {content[:200]}")
        return None
        
    except json.JSONDecodeError as e:
        logger.error(f"レスポンスの JSON パースに失敗: {e}")
        return None
    except ImportError:
        logger.error("requests パッケージが必要です: pip install requests")
        return None
    except Exception as e:
        logger.error(f"OpenAI API 呼び出しエラー: {e}")
        return None


def apply_classifications(
    activities: list[dict],
    classifications: list[dict],
    target_date: str,
    min_confidence: float = 0.5,
    dry_run: bool = False,
) -> dict:
    """LLM の分類結果をデータベースに適用する
    
    Returns:
        {"applied": int, "skipped": int, "errors": int, "details": list}
    """
    from .database import update_activity_tags_by_time
    
    db_path = get_db_path()
    applied = 0
    skipped = 0
    errors = 0
    details = []
    
    # index → 分類結果のマッピング
    cls_map = {}
    for c in classifications:
        idx = c.get("index", 0)
        cls_map[idx] = c
    
    for i, act in enumerate(activities):
        idx = i + 1
        cls = cls_map.get(idx)
        
        if not cls:
            skipped += 1
            continue
        
        confidence = cls.get("confidence", 0)
        if confidence < min_confidence:
            details.append({
                "index": idx,
                "app": act["app_name"],
                "status": "skipped",
                "reason": f"confidence {confidence} < {min_confidence}",
            })
            skipped += 1
            continue
        
        new_wp = cls.get("work_phase", "")
        new_pj = cls.get("project", "")
        
        # 変更がない場合はスキップ
        if new_wp == act.get("work_phase", "") and new_pj == act.get("project", ""):
            skipped += 1
            continue
        
        if dry_run:
            details.append({
                "index": idx,
                "app": act["app_name"],
                "title": (act.get("tab_title") or act.get("window_title", ""))[:60],
                "status": "would_apply",
                "old_wp": act.get("work_phase", ""),
                "new_wp": new_wp,
                "old_pj": act.get("project", ""),
                "new_pj": new_pj,
                "confidence": confidence,
            })
            applied += 1
            continue
        
        try:
            # 対象アクティビティの時間範囲で更新
            title = act.get("tab_title") or act.get("window_title", "")
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("""
                    UPDATE activity_log
                    SET work_phase = CASE WHEN ? != '' THEN ? ELSE work_phase END,
                        project = CASE WHEN ? != '' THEN ? ELSE project END
                    WHERE date(timestamp) = ?
                      AND app_name = ?
                      AND (tab_title = ? OR window_title = ? OR (tab_title IS NULL AND window_title = ?))
                      AND is_idle = 0
                """, (
                    new_wp, new_wp,
                    new_pj, new_pj,
                    target_date,
                    act["app_name"],
                    title, title, title,
                ))
                updated_count = cursor.rowcount
            
            details.append({
                "index": idx,
                "app": act["app_name"],
                "status": "applied",
                "updated_rows": updated_count,
                "new_wp": new_wp,
                "new_pj": new_pj,
                "confidence": confidence,
            })
            applied += 1
            
        except Exception as e:
            logger.error(f"分類適用エラー (index={idx}): {e}")
            errors += 1
    
    return {
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }


def classify_with_llm(
    target_date: str = None,
    dry_run: bool = False,
    min_confidence: float = 0.5,
) -> dict:
    """LLM を使って指定日のアクティビティを自動分類する（メインエントリポイント）
    
    Args:
        target_date: 対象日（YYYY-MM-DD）。None の場合は今日
        dry_run: True の場合、実際の更新は行わず結果をプレビュー
        min_confidence: この値以上の確信度の結果のみ適用
    
    Returns:
        {"success": bool, "message": str, ...}
    """
    if target_date is None:
        target_date = date.today().isoformat()
    
    config = get_llm_config()
    
    if not config["enabled"]:
        return {
            "success": False,
            "message": "LLM 分類は無効です。config.yaml で llm.enabled: true に設定してください。",
        }
    
    if not config["api_key"]:
        return {
            "success": False,
            "message": "OpenAI API キーが設定されていません。config.yaml の llm.api_key または環境変数 OPENAI_API_KEY を設定してください。",
        }
    
    # カテゴリ取得
    categories = get_available_categories()
    
    # 未分類アクティビティ取得
    activities = get_unclassified_activities(target_date, limit=config["batch_size"])
    
    if not activities:
        return {
            "success": True,
            "message": f"{target_date} のアクティビティはありません。",
            "applied": 0,
        }
    
    logger.info(f"LLM 分類開始: {target_date}, {len(activities)} 件")
    
    # プロンプト構築
    prompt = build_classification_prompt(
        activities,
        categories["task_categories"],
        categories["cost_categories"],
    )
    
    # API 呼び出し
    classifications = call_openai_api(prompt, config)
    
    if classifications is None:
        return {
            "success": False,
            "message": "LLM API の呼び出しに失敗しました。",
        }
    
    # 結果適用
    result = apply_classifications(
        activities, classifications, target_date,
        min_confidence=min_confidence,
        dry_run=dry_run,
    )
    
    mode = "プレビュー" if dry_run else "適用"
    return {
        "success": True,
        "message": f"LLM 分類 {mode}: {result['applied']} 件適用、{result['skipped']} 件スキップ、{result['errors']} 件エラー",
        "date": target_date,
        "total_activities": len(activities),
        **result,
    }


# CLI エントリポイント
if __name__ == "__main__":
    import argparse
    import sys
    
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from timereaper.config import load_config
    
    parser = argparse.ArgumentParser(description="LLM ベースのアクティビティ自動分類")
    parser.add_argument("--date", default=None, help="対象日 (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="プレビューモード（実際の更新なし）")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="最低確信度 (0.0-1.0)")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ")
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    load_config()
    result = classify_with_llm(
        target_date=args.date,
        dry_run=args.dry_run,
        min_confidence=args.min_confidence,
    )
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
