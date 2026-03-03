"""
TimeReaper - py2app セットアップスクリプト
macOS アプリケーションバンドル (.app) のビルドに使用します。

使い方:
    python setup.py py2app
    python setup.py py2app --alias  (開発用: シンボリックリンクビルド)
"""

import re
from setuptools import setup


def get_version():
    """timereaper/__init__.py からバージョンを動的に読み込む"""
    with open("timereaper/__init__.py", "r") as f:
        content = f.read()
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not match:
        raise RuntimeError("バージョン情報が見つかりません")
    return match.group(1)


VERSION = get_version()

APP = ["main.py"]
DATA_FILES = [
    ("../Resources", ["config.yaml"]),
    ("../Resources/timereaper/templates", [
        "timereaper/templates/dashboard.html",
        "timereaper/templates/summary.html",
        "timereaper/templates/weekly.html",
        "timereaper/templates/settings.html",
    ]),
]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "assets/AppIcon.icns" if __import__("os").path.exists("assets/AppIcon.icns") else None,
    "plist": {
        "CFBundleName": "TimeReaper",
        "CFBundleDisplayName": "TimeReaper",
        "CFBundleIdentifier": "com.timereaper.app",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "LSUIElement": True,  # メニューバーアプリとしてDockに表示しない
        "NSAppleEventsUsageDescription": "TimeReaper needs access to System Events to monitor active windows.",
        "NSAccessibilityUsageDescription": "TimeReaper needs accessibility access to detect the active window.",
    },
    "packages": [
        "timereaper",
        "timereaper.integrations",
        "flask",
        "jinja2",
        "rumps",
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
    ],
    "includes": [
        "timereaper.config",
        "timereaper.monitor",
        "timereaper.classifier",
        "timereaper.database",
        "timereaper.dashboard",
        "timereaper.menubar",
        "urllib3.contrib.resolver",
        "urllib3.contrib.resolver.system",
        "urllib3.contrib.resolver._system",
    ],
    "excludes": [
        "tkinter",
        "unittest",
        "test",
    ],
}

setup(
    app=APP,
    name="TimeReaper",
    version=VERSION,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
