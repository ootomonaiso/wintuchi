"""トレイアイコン画像の生成（Pillow）."""
from __future__ import annotations

from PIL import Image, ImageDraw

from .model import Severity


def make_icon(severity: Severity = Severity.OK, size: int = 64,
              color: str | None = None) -> Image.Image:
    """状態色の丸＋温度計風アイコンを生成する。

    ``color`` を渡すとその色を使う（設定でカスタムした状態色の反映用）。
    省略時は ``severity.color``（既定色）。
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = color or severity.color

    # 背景の角丸四角（ダークベース）
    d.rounded_rectangle([2, 2, size - 2, size - 2], radius=size // 6,
                        fill=(40, 42, 48, 255))

    # 温度計（棒＋球）
    cx = size // 2
    bulb_r = size // 6
    bulb_cy = size - size // 4
    stem_top = size // 5
    stem_w = size // 10
    d.rounded_rectangle(
        [cx - stem_w, stem_top, cx + stem_w, bulb_cy],
        radius=stem_w, fill=(225, 225, 225, 255))
    d.ellipse([cx - bulb_r, bulb_cy - bulb_r, cx + bulb_r, bulb_cy + bulb_r],
              fill=color)
    # 水銀柱
    d.rounded_rectangle(
        [cx - stem_w // 2, stem_top + 4, cx + stem_w // 2, bulb_cy],
        radius=stem_w // 2, fill=color)

    # 右上に状態ドット
    dot_r = size // 8
    d.ellipse([size - dot_r * 2 - 4, 4, size - 4, dot_r * 2 + 4], fill=color)
    return img


def save_ico(path: str) -> None:
    """exe 用の .ico を出力（複数サイズ同梱）."""
    base = make_icon(Severity.OK, 256)
    base.save(path, format="ICO",
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
