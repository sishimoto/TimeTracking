#!/usr/bin/env python3
"""
TimeReaper アプリアイコン生成スクリプト
Pillow を使用して .icns ファイルを生成します。

使い方:
    pip install Pillow
    python scripts/generate_icon.py
"""

import subprocess
import tempfile
import os
import sys


def create_icon_with_sips():
    """macOS の sips コマンドで .icns を生成（Pillow 不要）"""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
    os.makedirs(output_dir, exist_ok=True)
    icns_path = os.path.join(output_dir, "AppIcon.icns")

    # まず PNG を Python で生成（Pillow なしの場合は手動配置を案内）
    try:
        from PIL import Image, ImageDraw, ImageFont
        has_pillow = True
    except ImportError:
        has_pillow = False

    if not has_pillow:
        # Pillow なし: プレースホルダーの手順を表示
        print("⚠️  Pillow がインストールされていません")
        print("   以下のいずれかの方法でアイコンを用意してください:")
        print("")
        print("   方法1: Pillow をインストールして再実行")
        print("     pip install Pillow && python scripts/generate_icon.py")
        print("")
        print("   方法2: 1024x1024 の PNG を assets/AppIcon.png に配置して再実行")
        print("")
        print("   方法3: アイコンなしでビルド（デフォルトアイコンが使われます）")

        # assets/AppIcon.png が既にある場合はそれを変換
        png_path = os.path.join(output_dir, "AppIcon.png")
        if os.path.exists(png_path):
            print(f"\n✅ {png_path} を検出しました。.icns に変換します...")
            _png_to_icns(png_path, icns_path)
            return icns_path
        return None

    # Pillow で PNG を生成
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景: 角丸四角（macOS スタイル）
    margin = 40
    radius = 180
    bg_color = (22, 27, 34, 255)  # #161b22
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=bg_color,
    )

    # タイマーアイコン ⏱ をテキストとして描画
    accent_color = (88, 166, 255, 255)  # #58a6ff
    # 円（時計の外枠）
    cx, cy = size // 2, size // 2 + 20
    r = 300
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent_color, width=30)

    # 時計の針
    import math
    # 時針
    angle_h = math.radians(-60)
    hx = cx + int(180 * math.sin(angle_h))
    hy = cy - int(180 * math.cos(angle_h))
    draw.line([(cx, cy), (hx, hy)], fill=accent_color, width=24)
    # 分針
    angle_m = math.radians(0)
    mx = cx + int(240 * math.sin(angle_m))
    my = cy - int(240 * math.cos(angle_m))
    draw.line([(cx, cy), (mx, my)], fill=accent_color, width=16)
    # 中心点
    draw.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=accent_color)

    # テキスト "TT"
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 140)
    except (OSError, IOError):
        font = ImageFont.load_default()
    draw.text((cx, cy + r + 60), "TT", fill=accent_color, font=font, anchor="mt")

    # PNG として保存
    png_path = os.path.join(output_dir, "AppIcon.png")
    img.save(png_path, "PNG")
    print(f"✅ PNG アイコンを生成: {png_path}")

    # .icns に変換
    _png_to_icns(png_path, icns_path)
    return icns_path


def _png_to_icns(png_path: str, icns_path: str):
    """PNG を macOS の iconutil で .icns に変換"""
    with tempfile.TemporaryDirectory() as tmpdir:
        iconset_dir = os.path.join(tmpdir, "AppIcon.iconset")
        os.makedirs(iconset_dir)

        # 必要なサイズの PNG を生成
        sizes = [16, 32, 64, 128, 256, 512, 1024]
        for s in sizes:
            # 標準解像度
            out = os.path.join(iconset_dir, f"icon_{s}x{s}.png")
            subprocess.run(
                ["sips", "-z", str(s), str(s), png_path, "--out", out],
                capture_output=True,
            )
            # Retina (@2x)
            if s <= 512:
                out2x = os.path.join(iconset_dir, f"icon_{s//2}x{s//2}@2x.png")
                if s // 2 >= 16:
                    subprocess.run(
                        ["sips", "-z", str(s), str(s), png_path, "--out", out2x],
                        capture_output=True,
                    )

        # iconutil で .icns に変換
        result = subprocess.run(
            ["iconutil", "-c", "icns", iconset_dir, "-o", icns_path],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"✅ .icns アイコンを生成: {icns_path}")
        else:
            print(f"❌ .icns 変換に失敗: {result.stderr}")


if __name__ == "__main__":
    result = create_icon_with_sips()
    if result:
        print(f"\n🎉 アイコン生成完了: {result}")
    else:
        print("\n⚠️  アイコンが生成されませんでした")
