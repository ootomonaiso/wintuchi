"""共通デザイントークン（配色・フォント・角丸・バッジ・ゲージ）.

3画面（フライアウト / 常駐ウィジェット / 設定）で見た目を統一するための
単一の情報源。色は (light, dark) のタプルで持ち、CustomTkinter ウィジェットには
そのまま渡せる。生の tk.Canvas 等には ``resolve()`` で現在モードの色へ解決する。
"""
from __future__ import annotations

import customtkinter as ctk

from .model import Severity

# ===================== 配色（(light, dark)） =====================
WINDOW = ("#f3f4f6", "#16181d")        # ウィンドウ地
CARD = ("#ffffff", "#232730")          # カード面
CARD_ALT = ("#f7f8fa", "#1e222a")      # 一段沈めた面（セクション等）
INSET = ("#eceef2", "#2b303a")         # 入力欄・バーの溝
BORDER = ("#e4e7ec", "#343a45")        # 細い境界線
BORDER_STRONG = ("#d2d6de", "#424956")  # 強めの境界線

TEXT = ("#1b1f27", "#e9ebef")          # 本文
MUTED = ("#5e6570", "#9aa1ac")         # 補助テキスト
FAINT = ("#8b919c", "#6b7280")         # さらに薄い（更新時刻など）

ACCENT = ("#2f6fd6", "#5b9bf5")        # 既定アクセント（ボタン等）
ACCENT_HOVER = ("#2760bd", "#4f8dec")
ACCENT_TEXT = "#ffffff"

LUX = "#4a90d9"                         # 照度バーの中立色（単色）

# ===================== 状態（Severity）の配色 =====================
# バー/枠/ドットに使う単色（モード非依存。彩度はやや抑える）
SEV_COLOR: dict[Severity, str] = {
    Severity.OK: "#3BA55D",
    Severity.WARN: "#E8A33D",
    Severity.CRITICAL: "#E24C4C",
    Severity.STALE: "#8A8A8A",
}
# 状態バッジの淡い地色 (light, dark)
SEV_SOFT: dict[Severity, tuple[str, str]] = {
    Severity.OK: ("#e7f4ec", "#1d3326"),
    Severity.WARN: ("#fbf0db", "#39301b"),
    Severity.CRITICAL: ("#fce3e3", "#3a2020"),
    Severity.STALE: ("#ececef", "#2b2f38"),
}
# 状態バッジ・値の文字色 (light, dark)
SEV_TEXT: dict[Severity, tuple[str, str]] = {
    Severity.OK: ("#1f7a46", "#6fcf97"),
    Severity.WARN: ("#976312", "#f0b45a"),
    Severity.CRITICAL: ("#b22d2d", "#ff8f8f"),
    Severity.STALE: ("#5e6570", "#aab2bd"),
}

# ===================== 角丸・余白 =====================
R_CARD = 12
R_INPUT = 8
R_PILL = 20

PAD = 12          # 基準パディング
GAP = 6           # 要素間の基準ギャップ

# ===================== セグメントバー =====================
SEG_N = 14
SEG_GAP = 2
SEG_W = 130
SEG_H = 9


def resolve(color) -> str:
    """(light, dark) タプル or 単色 を、現在の外観モードの単色に解決する。"""
    if isinstance(color, (tuple, list)):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color


def font(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    """CTkFont を生成（root 生成後に呼ぶこと）。"""
    return ctk.CTkFont(size=size, weight=weight)


def make_segbar(parent, frac: float, color: str, *, surface=CARD,
                width: int = SEG_W, height: int = SEG_H,
                n: int = SEG_N) -> "ctk.CTkCanvas":
    """分割ブロック状のプログレスバーを Canvas で描画する。

    ``surface`` はバーが乗る面の色（Canvas は透明にできないため地色を合わせる）。
    """
    import tkinter as tk

    bg = resolve(surface)
    empty = resolve(INSET)
    c = tk.Canvas(parent, width=width, height=height, bg=bg,
                  highlightthickness=0, bd=0)
    seg_w = (width - (n - 1) * SEG_GAP) / n
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * n))
    if frac > 0 and filled == 0:
        filled = 1  # わずかでも値があれば最低1セル点灯
    r = max(1, height // 2)
    for i in range(n):
        x0 = i * (seg_w + SEG_GAP)
        col = color if i < filled else empty
        _round_rect(c, x0, 0, x0 + seg_w, height, r, col)
    return c


def _round_rect(canvas, x0, y0, x1, y1, r, fill) -> None:
    """角丸矩形を Canvas に描く（細セル向けの簡易版）。"""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    canvas.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=fill, outline="")
    canvas.create_oval(x1 - 2 * r, y0, x1, y0 + 2 * r, fill=fill, outline="")
    canvas.create_oval(x0, y1 - 2 * r, x0 + 2 * r, y1, fill=fill, outline="")
    canvas.create_oval(x1 - 2 * r, y1 - 2 * r, x1, y1, fill=fill, outline="")
    canvas.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline="")
    canvas.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline="")


def label_for(sev: Severity, cfg: dict | None) -> str:
    """設定の labels を優先して状態の表示名を返す（未設定は既定）。"""
    labels = (cfg or {}).get("labels") if cfg else None
    if isinstance(labels, dict):
        v = labels.get(sev.key)
        if isinstance(v, str) and v.strip():
            return v
    return sev.label
