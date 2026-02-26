"""
TimeTracker - py2app セットアップスクリプト
macOS アプリケーションバンドル (.app) のビルドに使用します。

使い方:
    python setup.py py2app
"""

from setuptools import setup

APP = ["main.py"]
DATA_FILES = [
    ("../Resources", ["config.yaml"]),
    ("../Resources/timetracker/templates", ["timetracker/templates/dashboard.html"]),
]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": None,  # TODO: アイコンファイルを追加する場合はここに指定
    "plist": {
        "CFBundleName": "TimeTracker",
        "CFBundleDisplayName": "TimeTracker",
        "CFBundleIdentifier": "com.timetracker.app",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": True,  # メニューバーアプリとしてDockに表示しない
        "NSAppleEventsUsageDescription": "TimeTracker needs access to System Events to monitor active windows.",
        "NSAccessibilityUsageDescription": "TimeTracker needs accessibility access to detect the active window.",
    },
    "packages": [
        "timetracker",
        "timetracker.integrations",
        "flask",
        "jinja2",
        "rumps",
    ],
    "includes": [
        "timetracker.config",
        "timetracker.monitor",
        "timetracker.classifier",
        "timetracker.database",
        "timetracker.dashboard",
        "timetracker.menubar",
    ],
    "excludes": [
        "tkinter",
        "unittest",
        "test",
    ],
}

setup(
    app=APP,
    name="TimeTracker",
    version="0.1.0",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
