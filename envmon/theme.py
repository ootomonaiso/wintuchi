"""共通デザイントークン（配色・状態バッジ）.

ヘッドレス化以降、描画は Rust オーバーレイ側が担うため Tk 依存は持たない。
ここは「色の単一の情報源」。色は (light, dark) のタプルで持ち、
``resolve()`` で現在の外観モード（Windows のレジストリ設定）の単色へ解決する。
"""
from __future__ import annotations

import re

from .model import Severity

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

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


def system_uses_light_theme() -> bool:
    """Windows の「アプリの既定モード」が Light かをレジストリから読む。失敗時は True。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        try:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(val)
        finally:
            winreg.CloseKey(key)
    except OSError:
        return True


def resolve(color) -> str:
    """(light, dark) タプル or 単色 を、現在の外観モードの単色に解決する。"""
    if isinstance(color, (tuple, list)):
        return color[0] if system_uses_light_theme() else color[1]
    return color


def label_for(sev: Severity, cfg: dict | None) -> str:
    """設定の labels を優先して状態の表示名を返す（未設定は既定）。"""
    labels = (cfg or {}).get("labels") if cfg else None
    if isinstance(labels, dict):
        v = labels.get(sev.key)
        if isinstance(v, str) and v.strip():
            return v
    return sev.label


def is_hex_color(v) -> bool:
    """``#RGB`` / ``#RRGGBB`` 形式かを判定する。"""
    return isinstance(v, str) and bool(_HEX_RE.match(v.strip()))


def color_for(sev: Severity, cfg: dict | None) -> str:
    """設定の colors を優先して状態色（単色）を返す（未設定/不正は既定）。"""
    colors = (cfg or {}).get("colors") if cfg else None
    if isinstance(colors, dict):
        v = colors.get(sev.key)
        if is_hex_color(v):
            return v
    return sev.color


def lux_color(cfg: dict | None) -> str:
    """設定の colors.lux を優先して照度バーの中立色を返す（未設定/不正は既定）。"""
    colors = (cfg or {}).get("colors") if cfg else None
    if isinstance(colors, dict):
        v = colors.get("lux")
        if is_hex_color(v):
            return v
    return LUX
