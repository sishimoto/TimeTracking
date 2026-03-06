"""
TimeReaper アップデートチェッカー
GitHub Releases API を使用して最新バージョンを確認し、
アップデート通知と自動更新を提供する。
"""

import logging
import re
import subprocess
import sys
import os
import threading
from dataclasses import dataclass
from typing import Optional

import requests

from timereaper import __version__

logger = logging.getLogger(__name__)

# GitHub リポジトリ情報
GITHUB_OWNER = "sishimoto"
GITHUB_REPO = "TimeReaper"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_ALL_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_TAGS_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/tags"


@dataclass
class UpdateInfo:
    """アップデート情報"""
    current_version: str
    latest_version: str
    is_update_available: bool
    release_url: str = ""
    release_notes: str = ""
    download_url: str = ""
    published_at: str = ""


def parse_version(version_str: str) -> tuple[int, ...]:
    """バージョン文字列をタプルに変換（比較用）
    
    '0.2.0' → (0, 2, 0)
    'v0.2.0' → (0, 2, 0)
    """
    cleaned = version_str.strip().lstrip("v")
    parts = re.findall(r'\d+', cleaned)
    return tuple(int(p) for p in parts)


def check_for_updates(timeout: int = 5) -> Optional[UpdateInfo]:
    """GitHub Releases API とタグの両方を確認し、最新バージョンを返す

    Release（pre-release 含む）とタグを両方チェックし、
    より新しいバージョンを採用する。タグのみ（Release 未作成）の場合も検出可能。

    Args:
        timeout: API リクエストのタイムアウト（秒）

    Returns:
        UpdateInfo: アップデート情報。取得失敗時は None
    """
    current = __version__
    logger.debug(f"アップデートチェック開始: 現在 v{current}")

    try:
        headers = {"Accept": "application/vnd.github.v3+json"}

        # --- 1. GitHub Releases から最新を取得 ---
        release_info = None
        release_version: tuple[int, ...] = (0,)

        response = requests.get(
            GITHUB_ALL_RELEASES_URL, headers=headers, timeout=timeout,
            params={"per_page": 10},
        )

        if response.status_code == 200:
            releases = response.json()
            best = None
            best_version: tuple[int, ...] = (0,)
            for rel in releases:
                if rel.get("draft", False):
                    continue
                tag = rel.get("tag_name", "")
                ver = _parse_release_version(tag)
                if ver > best_version:
                    best_version = ver
                    best = rel

            if best is not None:
                release_version = best_version
                latest_tag = best.get("tag_name", "")
                latest_version = latest_tag.lstrip("v")

                # DMG のダウンロード URL を探す
                download_url = ""
                for asset in best.get("assets", []):
                    if asset.get("name", "").endswith(".dmg"):
                        download_url = asset.get("browser_download_url", "")
                        break

                release_info = UpdateInfo(
                    current_version=current,
                    latest_version=latest_version,
                    is_update_available=best_version > parse_version(current),
                    release_url=best.get("html_url", ""),
                    release_notes=best.get("body", ""),
                    download_url=download_url,
                    published_at=best.get("published_at", ""),
                )

        # --- 2. タグから最新を取得（Release 未作成のバージョンも検出） ---
        tag_info = _check_tags_fallback(current, timeout)
        tag_version: tuple[int, ...] = (0,)
        if tag_info is not None:
            tag_version = _parse_release_version(tag_info.latest_version)

        # --- 3. Release とタグのうち、より新しい方を採用 ---
        if tag_info is not None and tag_version > release_version:
            logger.debug(f"タグ v{tag_info.latest_version} が Release より新しい")
            result = tag_info
        elif release_info is not None:
            result = release_info
        elif tag_info is not None:
            result = tag_info
        else:
            logger.debug("リリースもタグも見つかりません")
            return None

        if result.is_update_available:
            logger.info(f"新バージョンあり: v{result.latest_version} (現在: v{current})")
        else:
            logger.debug(f"最新版です: v{current}")

        return result

    except requests.exceptions.Timeout:
        logger.warning("アップデートチェック: タイムアウト")
        return None
    except requests.exceptions.ConnectionError:
        logger.warning("アップデートチェック: ネットワーク接続エラー")
        return None
    except Exception as e:
        logger.warning(f"アップデートチェック失敗: {e}")
        return None


def _parse_release_version(tag: str) -> tuple[int, ...]:
    """リリースタグからバージョンタプルを生成する（-rc 等のサフィックスは無視）"""
    cleaned = tag.strip().lstrip("v")
    # "0.4.0-rc" → "0.4.0"
    base = re.split(r'[-+]', cleaned)[0]
    parts = re.findall(r'\d+', base)
    return tuple(int(p) for p in parts)


def _check_tags_fallback(current_version: str, timeout: int) -> Optional[UpdateInfo]:
    """GitHub Releases がない場合、タグから最新バージョンを確認"""
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        response = requests.get(GITHUB_TAGS_URL, headers=headers, timeout=timeout)
        
        if response.status_code != 200:
            return None
        
        tags = response.json()
        if not tags:
            return UpdateInfo(
                current_version=current_version,
                latest_version=current_version,
                is_update_available=False,
            )
        
        # バージョンタグ（v で始まる）をフィルタして最新を取得
        version_tags = []
        for tag in tags:
            name = tag.get("name", "")
            if re.match(r'^v?\d+\.\d+', name):
                version_tags.append(name)
        
        if not version_tags:
            return UpdateInfo(
                current_version=current_version,
                latest_version=current_version,
                is_update_available=False,
            )
        
        # 最新バージョンを取得
        version_tags.sort(key=lambda t: parse_version(t), reverse=True)
        latest_tag = version_tags[0]
        latest_version = latest_tag.lstrip("v")
        
        is_update = parse_version(latest_version) > parse_version(current_version)
        
        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_version,
            is_update_available=is_update,
            release_url=f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/{latest_tag}",
        )
        
    except Exception as e:
        logger.warning(f"タグ確認失敗: {e}")
        return None


def check_for_updates_async(callback) -> None:
    """バックグラウンドでアップデートチェックを実行
    
    Args:
        callback: UpdateInfo を引数に取るコールバック関数
    """
    def _worker():
        result = check_for_updates()
        if result and callback:
            callback(result)
    
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def perform_git_update() -> dict:
    """git pull でアップデートを実行する（開発環境向け）
    
    Returns:
        dict: {'success': bool, 'message': str, 'details': str}
    """
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    git_dir = os.path.join(project_dir, ".git")
    
    if not os.path.isdir(git_dir):
        return {
            "success": False,
            "message": "Git リポジトリではありません",
            "details": "自動アップデートは git clone されたインストール環境でのみ利用可能です。\n"
                       "DMG ダウンロードによる更新を試してください。",
        }
    
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=project_dir, timeout=10,
        )
        branch = result.stdout.strip()
        logger.info(f"現在のブランチ: {branch}")
        
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=project_dir, timeout=10,
        )
        if result.stdout.strip():
            return {
                "success": False,
                "message": "ローカルに未コミットの変更があります",
                "details": f"先に変更をコミットまたはスタッシュしてください:\n{result.stdout}",
            }
        
        logger.info("git pull 実行中...")
        result = subprocess.run(
            ["git", "pull", "origin", branch],
            capture_output=True, text=True, cwd=project_dir, timeout=60,
        )
        
        if result.returncode != 0:
            return {
                "success": False,
                "message": "git pull に失敗しました",
                "details": result.stderr,
            }
        
        pull_output = result.stdout.strip()
        
        venv_python = os.path.join(project_dir, "venv", "bin", "python")
        requirements = os.path.join(project_dir, "requirements.txt")
        
        if os.path.exists(venv_python) and os.path.exists(requirements):
            logger.info("依存パッケージを更新中...")
            result = subprocess.run(
                [venv_python, "-m", "pip", "install", "-r", requirements, "-q"],
                capture_output=True, text=True, cwd=project_dir, timeout=120,
            )
            if result.returncode != 0:
                logger.warning(f"pip install 警告: {result.stderr}")
        
        new_version = _get_installed_version(project_dir)
        
        return {
            "success": True,
            "message": f"v{new_version} にアップデートしました",
            "details": pull_output,
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": "アップデートがタイムアウトしました",
            "details": "ネットワーク接続を確認してください。",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"アップデートに失敗しました: {e}",
            "details": str(e),
        }


def perform_dmg_update(download_url: str) -> dict:
    """DMG をダウンロードして /Applications に自動インストールする（.app バンドル向け）

    1. DMG を一時ディレクトリにダウンロード
    2. DMG をマウント
    3. TimeReaper.app を /Applications にコピー
    4. DMG をアンマウント・削除
    5. 新しい .app を起動して自分自身を終了

    Returns:
        dict: {'success': bool, 'message': str, 'details': str}
    """
    import tempfile
    import shutil

    if not download_url:
        return {
            "success": False,
            "message": "ダウンロード URL がありません",
            "details": "GitHub Release に DMG アセットが見つかりません。",
        }

    tmpdir = None
    mount_point = None
    try:
        # 1. ダウンロード
        tmpdir = tempfile.mkdtemp(prefix="timereaper_update_")
        dmg_path = os.path.join(tmpdir, "TimeReaper.dmg")
        logger.info(f"DMG ダウンロード中: {download_url}")

        resp = requests.get(download_url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(dmg_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"DMG ダウンロード完了: {os.path.getsize(dmg_path)} bytes")

        # 2. DMG マウント
        mount_point = os.path.join(tmpdir, "dmg_mount")
        os.makedirs(mount_point, exist_ok=True)
        result = subprocess.run(
            ["hdiutil", "attach", dmg_path, "-mountpoint", mount_point, "-nobrowse", "-quiet"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "message": "DMG のマウントに失敗しました",
                "details": result.stderr,
            }

        # 3. TimeReaper.app を探す
        app_src = os.path.join(mount_point, "TimeReaper.app")
        if not os.path.isdir(app_src):
            # DMG 直下にない場合サブディレクトリを探す
            for item in os.listdir(mount_point):
                candidate = os.path.join(mount_point, item, "TimeReaper.app")
                if os.path.isdir(candidate):
                    app_src = candidate
                    break

        if not os.path.isdir(app_src):
            return {
                "success": False,
                "message": "DMG 内に TimeReaper.app が見つかりません",
                "details": f"マウント先: {mount_point}, 内容: {os.listdir(mount_point)}",
            }

        # 4. /Applications にコピー
        app_dest = "/Applications/TimeReaper.app"
        if os.path.exists(app_dest):
            logger.info(f"既存アプリを削除: {app_dest}")
            shutil.rmtree(app_dest)

        logger.info(f"コピー: {app_src} → {app_dest}")
        shutil.copytree(app_src, app_dest)

        # 5. アンマウント
        subprocess.run(
            ["hdiutil", "detach", mount_point, "-quiet"],
            capture_output=True, timeout=10,
        )

        # 6. 新しいアプリを起動（遅延実行してから自分を終了）
        logger.info("新しいバージョンを起動します...")
        subprocess.Popen(
            ["bash", "-c", f"sleep 2 && open '{app_dest}'"],
            start_new_session=True,
        )

        return {
            "success": True,
            "message": "アップデート完了。アプリを再起動します...",
            "details": f"インストール先: {app_dest}",
            "restart": True,
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"ダウンロードに失敗しました: {e}",
            "details": str(e),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"アップデートに失敗しました: {e}",
            "details": str(e),
        }
    finally:
        # クリーンアップ
        if mount_point and os.path.ismount(mount_point):
            subprocess.run(["hdiutil", "detach", mount_point, "-quiet"],
                           capture_output=True, timeout=10)
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


def _get_installed_version(project_dir: str) -> str:
    """プロジェクトディレクトリから最新のバージョンを読み込む"""
    init_path = os.path.join(project_dir, "timereaper", "__init__.py")
    try:
        with open(init_path) as f:
            content = f.read()
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        return match.group(1) if match else __version__
    except Exception:
        return __version__
