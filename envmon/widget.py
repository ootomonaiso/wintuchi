"""常駐ウィジェット窓（参照アプリ流のコンパクトなミニパネル）.

2 モード:
  - "float"  : 任意位置に浮遊する小さなカードパネル（ドラッグ移動・位置記憶）。既定。
  - "taskbar": タスクバー矩形を検出し、その上に最前面オーバーレイを重ねて追従表示
               （Win11 はウィジェット埋め込み API が無いためオーバーレイ方式。
               ズレ/チラつきが出ることがあるため float を推奨）。
選択した (部屋, 指標) をチップで表示する。
"""
from __future__ import annotations

import logging
from typing import Callable

import customtkinter as ctk

from taskwidget import geometry  # タスクバー検出/作業領域は共通ライブラリに集約

from . import theme
from .flyout import _gauge_spec
from .model import AppState, Severity

log = logging.getLogger(__name__)

_METRIC_INFO = {
    "temp": ("気温", "℃"),
    "humid": ("湿度", "%"),
    "lux": ("照度", "lx"),  # 情報表示のみ（監視はしない。通知ゲート用）
}

WIDGET_W = 300            # float モードの幅
TASKBAR_KEY = "#010101"   # 透過キー色（この色のピクセルを透明化＝背景透明）
TASKBAR_FG = "#c9ccd1"    # タスクバー上のラベル色（明色固定）


class DesktopWidget:
    def __init__(self, master, state: AppState, config,
                 on_settings: Callable[[], None]):
        self.state = state
        self.config = config
        self._on_settings = on_settings
        self._visible = False
        self._drag = (0, 0)
        self._drag_origin = (0, 0)
        self._dragging = False            # 閾値を超えて実際に動かし始めたか
        self._last_geom = None            # 直近に適用した geometry（重複適用の抑止）
        self._follow_job = None

        self.win = ctk.CTkToplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", float(config.get("widget", {}).get("opacity", 0.96)))
        except Exception:
            pass

        # ヘッダ（float モードのみ表示）
        self._header = ctk.CTkFrame(self.win, fg_color=theme.CARD_ALT,
                                    corner_radius=0, height=26)
        self._title = ctk.CTkLabel(self._header, text="環境モニタ",
                                   font=theme.font(10, "bold"),
                                   text_color=theme.MUTED)
        self._title.pack(side="left", padx=10)
        ctk.CTkButton(self._header, text="✕", width=20, height=20, corner_radius=6,
                      fg_color="transparent", hover_color=theme.INSET,
                      text_color=theme.MUTED,
                      font=theme.font(11), command=self.hide).pack(side="right", padx=(0, 4))
        ctk.CTkButton(self._header, text="⚙", width=20, height=20, corner_radius=6,
                      fg_color="transparent", hover_color=theme.INSET,
                      text_color=theme.MUTED,
                      font=theme.font(11), command=self._on_settings).pack(side="right")

        self._body = ctk.CTkFrame(self.win, fg_color="transparent")

        for w in (self._header, self._title):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

    # --- モード ---
    def _dock(self) -> str:
        return self.config.get("widget", {}).get("dock", "taskbar")

    # --- 表示制御 ---
    def apply_enabled(self) -> None:
        if self.config.get("widget", {}).get("enabled"):
            self.show()
        else:
            self.hide()

    def show(self) -> None:
        dock = self._dock()
        self._layout(dock)
        self.refresh()
        self.win.update_idletasks()
        # タスクバー追従モードは保存位置を無視して常に追従する
        # （過去のドラッグで pos が残っていても追従が止まらないように）。
        g = geometry.find_taskbar()
        if dock == "taskbar" and g and g.horizontal:
            self._position_taskbar()
            self._start_follow()
        else:
            self._position_float()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self._visible = True

    def hide(self) -> None:
        self._stop_follow()
        self.win.withdraw()
        self._visible = False

    def toggle(self) -> None:
        new_enabled = not self._visible
        w = dict(self.config.get("widget", {}))
        w["enabled"] = new_enabled
        self.config.update(widget=w)
        self.apply_enabled()

    def _layout(self, dock: str) -> None:
        """モードに応じてヘッダ表示/非表示・地色を切替える。"""
        self._body.pack_forget()
        if dock == "taskbar":
            self._header.pack_forget()
            # 背景を透明化: 地色=透過キー色にし、その色のピクセルを透明にする。
            # これでタスクバーの黒い箱が消え、文字だけがタスクバー上に乗る。
            self.win.configure(fg_color=TASKBAR_KEY)
            try:
                self.win.attributes("-transparentcolor", TASKBAR_KEY)
            except Exception:
                pass
            # タスクバー高さ(約48px)に収めるため余白は最小限。縦中央寄せ。
            self._body.pack(fill="both", expand=True, padx=8, pady=0)
        else:
            self._header.pack(fill="x")
            try:
                self.win.attributes("-transparentcolor", "")  # 透明化を解除
            except Exception:
                pass
            self.win.configure(fg_color=theme.CARD)
            self._body.pack(fill="both", expand=True, padx=10, pady=(6, 10))

    # --- 位置決め ---
    def _apply_geometry(self, spec: str) -> bool:
        """geometry を適用する。前回と同じなら何もしない（無駄な再描画＝ちらつき防止）。"""
        if spec == self._last_geom:
            return False
        self.win.geometry(spec)
        self._last_geom = spec
        return True

    def _position_float(self) -> None:
        pos = self.config.get("widget", {}).get("pos")
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        if pos and "x" in pos and "y" in pos:
            x, y = int(pos["x"]), int(pos["y"])
        else:
            left, top, right, bottom = geometry.work_area()
            x = right - w - 16
            y = bottom - h - 16
        self._apply_geometry(f"{w}x{h}+{x}+{y}")

    def _manual_pos(self) -> bool:
        pos = self.config.get("widget", {}).get("pos")
        return bool(pos and "x" in pos and "y" in pos)

    def _taskbar_gap(self) -> int:
        try:
            return max(0, int(self.config.get("widget", {}).get("taskbar_gap", 8)))
        except (TypeError, ValueError):
            return 8

    def _taskbar_xy(self, g: geometry.TaskbarInfo, w: int, h: int) -> tuple[int, int]:
        """トレイ左端から gap だけ離した位置を、タスクバー内にクランプして返す。"""
        x = g.tray_left - w - self._taskbar_gap()
        x = max(g.left + 4, min(x, g.tray_left - w - 2))
        y = g.top + max(0, (g.height - h) // 2)
        return x, y

    def _position_taskbar(self) -> bool:
        g = geometry.find_taskbar()
        if not g or not g.horizontal:
            self._position_float()
            return False
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        # タスクバーより背が高いと「浮いて」見えるので、必ずバー高さ内に収める。
        h = min(self.win.winfo_reqheight(), g.height)
        x, y = self._taskbar_xy(g, w, h)
        return self._apply_geometry(f"{w}x{h}+{x}+{y}")

    def reset_position(self) -> None:
        w = dict(self.config.get("widget", {}))
        w["pos"] = None            # float の記憶位置を消す
        w["taskbar_gap"] = 8       # taskbar の横位置を既定へ
        self.config.update(widget=w)
        if self._visible:
            self.show()

    def _start_follow(self) -> None:
        self._stop_follow()
        self._follow_job = self.win.after(1200, self._follow_tick)

    def _stop_follow(self) -> None:
        if self._follow_job is not None:
            try:
                self.win.after_cancel(self._follow_job)
            except Exception:
                pass
            self._follow_job = None

    def _follow_tick(self) -> None:
        if self._visible and self._dock() == "taskbar":
            # 位置が変わった時だけ前面化を再適用する（毎回やると微妙にちらつく）。
            if self._position_taskbar():
                self.win.lift()
                self.win.attributes("-topmost", True)
            self._follow_job = self.win.after(1200, self._follow_tick)

    # --- ドラッグ移動（全モードで有効。動かすと位置が固定される）---
    _DRAG_THRESHOLD = 4   # これ未満の移動はクリックとみなし動かさない

    def _drag_start(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())
        self._drag_origin = (e.x_root, e.y_root)
        self._dragging = False

    def _drag_move(self, e):
        if not self._dragging:
            ox, oy = self._drag_origin
            if abs(e.x_root - ox) < self._DRAG_THRESHOLD and \
               abs(e.y_root - oy) < self._DRAG_THRESHOLD:
                return  # クリックの微動。まだ動かさない（ちらつき防止）
            self._dragging = True
        nx = e.x_root - self._drag[0]
        if self._dock() == "taskbar":
            # タスクバー内では横のみ移動（縦はバー内に固定）。バー外へは出さない。
            g = geometry.find_taskbar()
            if g and g.horizontal:
                w = self.win.winfo_reqwidth()
                h = min(self.win.winfo_reqheight(), g.height)
                nx = max(g.left + 4, min(nx, g.tray_left - w - 2))
                ny = g.top + max(0, (g.height - h) // 2)
                self.win.geometry(f"+{nx}+{ny}")
                return
        self.win.geometry(f"+{nx}+{e.y_root - self._drag[1]}")

    def _drag_end(self, _e):
        if not self._dragging:
            return  # 動かしていない＝ただのクリック。再配置も保存もしない。
        self._dragging = False
        self._last_geom = None  # ドラッグ後は追従計算を一度通す
        if self._dock() == "taskbar":
            # 横移動量を「トレイ左端からの間隔」として記憶（追従は維持）。
            g = geometry.find_taskbar()
            if g and g.horizontal:
                w = self.win.winfo_reqwidth()
                gap = max(0, g.tray_left - (self.win.winfo_x() + w))
                wd = dict(self.config.get("widget", {}))
                wd["taskbar_gap"] = int(gap)
                self.config.update(widget=wd)
            return
        # float モード: 自由位置を記憶。
        w = dict(self.config.get("widget", {}))
        w["pos"] = {"x": self.win.winfo_x(), "y": self.win.winfo_y()}
        self.config.update(widget=w)

    # --- 描画 ---
    def refresh(self) -> None:
        for c in self._body.winfo_children():
            c.destroy()
        items = self.config.get("widget", {}).get("items", [])
        rooms = {r.name: r for r in self.state.snapshot()}
        dock = self._dock()

        if not items:
            ctk.CTkLabel(self._body, text="⚙ 設定 → ウィジェットで表示項目を選択",
                         font=theme.font(11),
                         text_color=(TASKBAR_FG if dock == "taskbar" else theme.MUTED)
                         ).pack(anchor="w", pady=6, padx=2)
        elif dock == "taskbar":
            self._render_grid(items, rooms)
        else:
            self._render_rows(items, rooms)

        self._bind_drag_recursive(self._body)
        if dock == "taskbar" and self._visible:
            self.win.after(1, self._position_taskbar)

    def _item_value(self, it, rooms):
        room, metric = it.get("room"), it.get("metric")
        if metric not in _METRIC_INFO:
            return None
        label, unit = _METRIC_INFO[metric]
        rs = rooms.get(room)
        value, active = None, set()
        bounds = self.config.room_config(room) if room else {}
        if rs is not None and rs.latest is not None:
            value = getattr(rs.latest, metric, None)
            active = rs.active_alerts
        return room, metric, label, unit, value, active, bounds

    def _render_rows(self, items, rooms) -> None:
        """float モード: 1項目1行（ラベル / ミニバー / 値）で縦に並べる。"""
        for it in items:
            info = self._item_value(it, rooms)
            if info:
                self._row_float(self._body, info).pack(fill="x", pady=2)

    def _render_grid(self, items, rooms) -> None:
        """taskbar モード: 各項目を「部屋／値」の縦スタックにし、細い区切り線で横に並べる。"""
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(expand=True)  # 縦中央寄せ
        first = True
        for it in items:
            info = self._item_value(it, rooms)
            if not info:
                continue
            if not first:
                # チップ間の細い区切り線（透過地でも見えるよう淡色を直接指定）。
                ctk.CTkFrame(row, width=1, height=22, fg_color="#555a63"
                             ).pack(side="left", padx=11)
            self._chip_taskbar(row, info).pack(side="left")
            first = False

    def _row_float(self, parent, info):
        """float モードの行: 部屋名＋強調値（指標名は単位で分かるので省略、バー無し）。"""
        room, metric, _label, unit, value, active, bounds = info
        _frac, color, note = _gauge_spec(metric, value, bounds, active)
        alerting = (metric in active) or bool(note)

        row = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkFrame(row, width=6, height=6, corner_radius=3,
                     fg_color=(color if alerting else theme.resolve(theme.BORDER))
                     ).pack(side="left", padx=(2, 6))
        ctk.CTkLabel(row, text=room, font=theme.font(12),
                     text_color=theme.MUTED, anchor="w").pack(side="left")
        txt = "--" if value is None else f"{value:g}{unit}"
        ctk.CTkLabel(row, text=txt, font=theme.font(13, "bold"),
                     text_color=(color if alerting else theme.TEXT)).pack(side="right", padx=(12, 0))
        return row

    def _chip_taskbar(self, parent, info):
        """taskbar モードのチップ: 「部屋 / 値」を縦2行で表示。

        指標名は単位(℃/%/V/lx)で分かるので省略。異常は文字色（橙/赤）で表す。
        2行なので1行あたりを大きめにでき、タスクバー(≈48px)でも読みやすい。
        """
        room, metric, _label, unit, value, active, bounds = info
        _frac, color, note = _gauge_spec(metric, value, bounds, active)
        alerting = (metric in active) or bool(note)

        chip = ctk.CTkFrame(parent, fg_color="transparent")
        # 上段: 状態ドット＋部屋名。異常時のみドットを色付け（一目で危険箇所が分かる）。
        head = ctk.CTkFrame(chip, fg_color="transparent")
        head.pack(anchor="center")
        ctk.CTkFrame(head, width=6, height=6, corner_radius=3,
                     fg_color=(color if alerting else "transparent")
                     ).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(head, text=room, font=theme.font(9), height=15,
                     text_color=TASKBAR_FG).pack(side="left")
        txt = "--" if value is None else f"{value:g}{unit}"
        ctk.CTkLabel(chip, text=txt, font=theme.font(14, "bold"), height=20,
                     text_color=(color if alerting else "#ffffff")).pack(anchor="center")
        return chip

    def _bind_drag_recursive(self, widget) -> None:
        try:
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_drag_recursive(child)
