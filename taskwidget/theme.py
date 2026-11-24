"""デザイントークン（配色・フォント・角丸・セグメントバー）.

ウィジェットの見た目を一元管理する単一の情報源。色は ``(light, dark)`` の
タプルで持ち、CustomTkinter ウィジェットにはそのまま渡せる。生の tk.Canvas 等
には :func:`resolve` で現在モードの単色へ解決する。

状態色は文字列キー（"ok"/"warn"/"critical"/"stale"/"info"）で引く汎用設計。
アプリ固有の語彙（温度・電圧…）はここには持ち込まない。
"""
from __future__ import annotations

from typing import Union

import customtkinter as ctk

ColorSpec = Union[str, tuple[str, str]]

# ===================== 面・文字（(light, dark)） =====================
CARD = ("#ffffff", "#232730")          # カード面（float の地色）
CARD_ALT = ("#f7f8fa", "#1e222a")      # 一段沈めた面（ヘッダ等）
INSET = ("#eceef2", "#2b303a")         # バーの溝・ホバー
BORDER = ("#e4e7ec", "#343a45")        # 細い境界線

TEXT = ("#1b1f27", "#e9ebef")          # 本文
MUTED = ("#5e6570", "#9aa1ac")         # 補助テキスト
FAINT = ("#8b919c", "#6b7280")         # さらに薄い

ACCENT = ("#2f6fd6", "#5b9bf5")        # 既定アクセント

# タスクバー追従モードの既定色（ダークなバー前提。auto 検出で上書きされる）
TASKBAR_BG_DARK = "#1b1b1b"
TASKBAR_FG_DARK = "#c9ccd1"
TASKBAR_BG_LIGHT = "#f2f3f5"
TASKBAR_FG_LIGHT = "#2a2d33"

# ===================== 状態（status）の配色 =====================
# バー/ドットに使う単色（モード非依存）
STATUS_COLOR: dict[str, str] = {
    "ok": "#3BA55D",
    "warn": "#E8A33D",
    "critical": "#E24C4C",
    "stale": "#8A8A8A",
    "info": "#4a90d9",
}
# バッジの淡い地色 (light, dark)
STATUS_SOFT: dict[str, tuple[str, str]] = {
    "ok": ("#e7f4ec", "#1d3326"),
    "warn": ("#fbf0db", "#39301b"),
    "critical": ("#fce3e3", "#3a2020"),
    "stale": ("#ececef", "#2b2f38"),
    "info": ("#e4eef9", "#1c2a3a"),
}
# バッジ・値の文字色 (light, dark)
STATUS_TEXT: dict[str, tuple[str, str]] = {
    "ok": ("#1f7a46", "#6fcf97"),
    "warn": ("#976312", "#f0b45a"),
    "critical": ("#b22d2d", "#ff8f8f"),
    "stale": ("#5e6570", "#aab2bd"),
    "info": ("#2f6fd6", "#79b2f7"),
}


def status_color(status: str | None, default: ColorSpec = TEXT) -> ColorSpec:
    """状態キーに対応する強調色を返す。未知/None は default。"""
    if status and status in STATUS_COLOR:
        return STATUS_COLOR[status]
    return default


# ===================== 角丸・余白 =====================
R_CARD = 12
R_PILL = 20
PAD = 12
GAP = 6

# ===================== セグメントバー =====================
SEG_N = 14
SEG_GAP = 2
SEG_W = 120
SEG_H = 8


def resolve(color: ColorSpec) -> str:
    """(light, dark) タプル or 単色 を、現在の外観モードの単色へ解決する。"""
    if isinstance(color, (tuple, list)):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color


def font(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    """CTkFont を生成（root 生成後に呼ぶこと）。"""
    return ctk.CTkFont(size=size, weight=weight)


def make_segbar(parent, frac: float, color: str, *, surface: ColorSpec = CARD,
                width: int = SEG_W, height: int = SEG_H, n: int = SEG_N):
    """分割ブロック状のプログレスバーを Canvas で描く。

    ``surface`` はバーが乗る面の色（Canvas は透明にできないため地色を合わせる）。
    戻り値は ``tkinter.Canvas``。
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
