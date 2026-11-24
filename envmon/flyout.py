"""枠なしフライアウト（トレイ直上に出る部屋カード一覧）.

トレイアイコンから開くメインのポップアップ。参照アプリ流に、トレイ付近へ
コンパクトに出し、フォーカスが外れたら閉じる。見た目は theme.py に一元化。
"""
from __future__ import annotations

import ctypes
import logging
from typing import Callable, Optional

import customtkinter as ctk

from . import theme
from .model import AppState, RoomState, Severity

log = logging.getLogger(__name__)

PANEL_W = 376
MARGIN = 12

# 照度は閾値判定の対象外（ゲート用途）なので中立色
_LUX_COLOR = theme.LUX


def _display_range(metric: str, lo, hi) -> tuple[float, float]:
    """バーのスケールに使う表示レンジ (dlo, dhi)。"""
    if metric == "humid":
        return 0.0, 100.0
    if metric == "voltage":
        return 2.0, 3.6
    if metric == "lux":
        return 0.0, 1000.0
    # temp: 閾値の外側に少し余白をとる。閾値未設定なら既定レンジ。
    dlo = (lo - 5.0) if lo is not None else (hi - 20.0 if hi is not None else 0.0)
    dhi = (hi + 5.0) if hi is not None else (lo + 20.0 if lo is not None else 40.0)
    return dlo, dhi


def _gauge_spec(metric: str, value, bounds: dict, active: set) -> tuple[float, str, str]:
    """(fill 0..1, 色, 注記) を返す。閾値接近で緑→橙、超過/割れ・停止で赤。"""
    if value is None:
        return 0.0, theme.SEV_COLOR[Severity.STALE], ""
    b = bounds.get(metric, {}) if metric in ("temp", "humid", "voltage") else {}
    lo, hi = b.get("min"), b.get("max")
    dlo, dhi = _display_range(metric, lo, hi)
    span = (dhi - dlo) or 1.0
    frac = max(0.0, min(1.0, (value - dlo) / span))

    if metric == "lux":
        return frac, _LUX_COLOR, ""

    # アラート中（rules が active_alerts に登録）→ 赤/橙系
    if metric in active:
        sev = Severity.CRITICAL if metric == "voltage" else Severity.WARN
        color = theme.SEV_COLOR[sev]
        if hi is not None and value > hi:
            note = "(上限超)"
        elif lo is not None and value < lo:
            note = "(電圧低)" if metric == "voltage" else "(下限割)"
        else:
            note = ""
        return frac, color, note

    # 閾値接近（レンジの12%以内）→ 橙、それ以外 → 緑
    near = False
    if hi is not None and 0 <= (hi - value) <= 0.12 * span:
        near = True
    if lo is not None and 0 <= (value - lo) <= 0.12 * span:
        near = True
    sev = Severity.WARN if near else Severity.OK
    return frac, theme.SEV_COLOR[sev], ""


def _work_area() -> tuple[int, int, int, int]:
    """プライマリモニタの作業領域 (left, top, right, bottom)（タスクバー除く）."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        rect = RECT()
        SPI_GETWORKAREA = 0x0030
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return 0, 0, 1920, 1040


class Flyout:
    def __init__(self, master, state: AppState, config,
                 on_room_click: Callable[[str], None],
                 on_settings: Callable[[], None]):
        self.state = state
        self.config = config
        self._on_room_click = on_room_click
        self._on_settings = on_settings

        self.win = ctk.CTkToplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(fg_color=theme.WINDOW)

        # ヘッダ
        header = ctk.CTkFrame(self.win, fg_color="transparent")
        header.pack(fill="x", padx=theme.PAD + 2, pady=(theme.PAD, 2))
        ctk.CTkLabel(header, text="環境モニタ",
                     font=theme.font(16, "bold"),
                     text_color=theme.TEXT).pack(side="left")
        ctk.CTkButton(header, text="⚙  設定", width=70, height=28,
                      corner_radius=theme.R_INPUT,
                      fg_color="transparent", hover_color=theme.INSET,
                      text_color=theme.MUTED, font=theme.font(12),
                      command=self._on_settings).pack(side="right")

        # 概況ピル＋最終取得
        summary = ctk.CTkFrame(self.win, fg_color="transparent")
        summary.pack(fill="x", padx=theme.PAD + 2, pady=(0, 6))
        self._summary = ctk.CTkLabel(summary, text="", corner_radius=theme.R_PILL,
                                     font=theme.font(11, "bold"), width=10)
        self._summary.pack(side="left", ipadx=10, ipady=3)
        self._status = ctk.CTkLabel(summary, text="", font=theme.font(11),
                                    text_color=theme.FAINT)
        self._status.pack(side="right")

        # スクロール可能な部屋カード領域
        self._scroll = ctk.CTkScrollableFrame(self.win, fg_color="transparent",
                                              width=PANEL_W - 20, height=360)
        self._scroll.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        self._cards: dict[str, ctk.CTkFrame] = {}
        self._visible = False
        self.win.bind("<FocusOut>", self._on_focus_out)

    # --- 表示制御 ---
    def toggle(self) -> None:
        self.hide() if self._visible else self.show()

    def show(self) -> None:
        # 位置・中身を withdraw 中に確定してから一度だけ表示する（ちらつき防止）。
        self.refresh()
        self.win.update_idletasks()
        w = PANEL_W
        h = min(540, max(170, self.win.winfo_reqheight()))
        left, top, right, bottom = _work_area()
        x = right - w - MARGIN
        y = bottom - h - MARGIN
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.attributes("-topmost", True)  # 表示前に最前面指定（出した後に動かさない）
        self.win.deiconify()
        self.win.focus_force()
        self._visible = True

    def hide(self) -> None:
        self.win.withdraw()
        self._visible = False

    def _on_focus_out(self, _event=None) -> None:
        self.win.after(120, self._maybe_hide)

    def _maybe_hide(self) -> None:
        try:
            if self.win.focus_displayof() is None:
                self.hide()
        except Exception:
            self.hide()

    # --- 描画 ---
    def refresh(self) -> None:
        rooms = self.state.snapshot()
        cfg = self.config.snapshot()
        with self.state.lock:
            last_ok = self.state.last_poll_ok
            last_err = self.state.last_poll_error

        # 最終取得
        if last_err:
            self._status.configure(text=f"取得エラー: {last_err[:28]}",
                                   text_color=theme.SEV_TEXT[Severity.CRITICAL])
        elif last_ok:
            self._status.configure(text=f"最終取得 {last_ok.strftime('%H:%M:%S')}",
                                   text_color=theme.FAINT)
        else:
            self._status.configure(text="未取得", text_color=theme.FAINT)

        # 概況ピル
        self._update_summary(rooms, cfg)

        for c in self._cards.values():
            c.destroy()
        self._cards.clear()

        if not rooms:
            lbl = ctk.CTkLabel(self._scroll,
                               text="データがありません\n「⚙ 設定」で接続先URLを確認してください",
                               text_color=theme.MUTED, font=theme.font(12), justify="center")
            lbl.pack(pady=28)
            self._cards["__empty__"] = lbl
            return

        for rs in rooms:
            self._cards[rs.name] = self._build_card(rs, cfg)

    def _update_summary(self, rooms, cfg) -> None:
        worst = Severity.OK
        n_alert = 0
        for rs in rooms:
            if rs.severity != Severity.OK:
                n_alert += 1
            worst = max(worst, rs.severity)
        if not rooms:
            text = "部屋なし"
            worst = Severity.STALE
        elif n_alert == 0:
            text = f"すべて{theme.label_for(Severity.OK, cfg)}"
        else:
            text = f"{n_alert}件 {theme.label_for(worst, cfg)}"
        self._summary.configure(text=text, fg_color=theme.SEV_SOFT[worst],
                                text_color=theme.SEV_TEXT[worst])

    def _build_card(self, rs: RoomState, cfg: dict) -> ctk.CTkFrame:
        sev = rs.severity
        accent = theme.SEV_COLOR[sev] if sev != Severity.OK else theme.resolve(theme.BORDER_STRONG)

        card = ctk.CTkFrame(self._scroll, corner_radius=theme.R_CARD,
                            fg_color=theme.CARD, border_width=1,
                            border_color=theme.BORDER)
        card.pack(fill="x", pady=5, padx=2)

        # 左の状態アクセントバー + 本体
        stripe = ctk.CTkFrame(card, width=4, corner_radius=2, fg_color=accent)
        stripe.pack(side="left", fill="y", padx=(6, 0), pady=8)
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True)

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(top, text=rs.name, font=theme.font(14, "bold"),
                     text_color=theme.TEXT).pack(side="left")
        badge = ctk.CTkLabel(top, text=theme.label_for(sev, cfg),
                             fg_color=theme.SEV_SOFT[sev], corner_radius=theme.R_PILL,
                             text_color=theme.SEV_TEXT[sev], font=theme.font(10, "bold"))
        badge.pack(side="right", ipadx=9, ipady=2)

        r = rs.latest
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(4, 4))
        if r is not None:
            bounds = self.config.room_config(rs.name)
            self._gauge_row(grid, "気温", r.temp, "℃", "temp", bounds, rs.active_alerts)
            self._gauge_row(grid, "湿度", r.humid, "%", "humid", bounds, rs.active_alerts)
            self._gauge_row(grid, "照度", r.lux, "lx", "lux", bounds, rs.active_alerts)
        else:
            ctk.CTkLabel(grid, text="受信待ち…", text_color=theme.MUTED,
                         font=theme.font(12)).pack(anchor="w")

        foot = ctk.CTkFrame(body, fg_color="transparent")
        foot.pack(fill="x", padx=12, pady=(0, 10))
        last = rs.last_seen.strftime("%m/%d %H:%M:%S") if rs.last_seen else "--"
        ctk.CTkLabel(foot, text=f"更新 {last}", font=theme.font(10),
                     text_color=theme.FAINT).pack(side="left")
        ctk.CTkButton(foot, text="この部屋の設定", width=96, height=24,
                      corner_radius=theme.R_INPUT, font=theme.font(10),
                      fg_color="transparent", hover_color=theme.INSET,
                      text_color=theme.ACCENT, border_width=1, border_color=theme.BORDER,
                      command=lambda n=rs.name: self._on_room_click(n)).pack(side="right")

        # カード本体クリックでも設定へ（ボタン類は除く）
        for w in (card, body, top, grid):
            w.bind("<Button-1>", lambda e, n=rs.name: self._on_room_click(n))
        return card

    def _gauge_row(self, parent, label: str, value, unit: str, metric: str,
                   bounds: dict, active: set) -> None:
        """1指標を [ラベル][セグメントバー][値] の行で描画する。"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=label, width=34, anchor="w",
                     font=theme.font(11), text_color=theme.MUTED).pack(side="left")

        frac, color, note = _gauge_spec(metric, value, bounds, active)
        bar = theme.make_segbar(row, frac, color, surface=theme.CARD)
        bar.pack(side="left", padx=(2, 10))

        # 異常は値の文字色で表す（「上限超」等のテキストは出さない）。
        txt = "--" if value is None else f"{value:g}{unit}"
        alerting = (metric in active) or bool(note)
        val_color = color if alerting else theme.TEXT
        ctk.CTkLabel(row, text=txt, anchor="e", font=theme.font(12, "bold"),
                     text_color=val_color).pack(side="right")
