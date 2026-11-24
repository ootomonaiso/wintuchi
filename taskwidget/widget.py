"""タスクバー追従／浮遊ウィジェットの本体 :class:`TaskbarWidget`.

最小の使い方::

    import taskwidget as tw

    app = tw.TaskbarWidget(title="Monitor")
    cpu = app.chip("CPU", "--")

    @app.every(1000)                     # 1秒ごと
    def tick():
        cpu.update(value=f"{read_cpu():.0f}%",
                   status="warn" if read_cpu() > 80 else "ok")

    app.run()

既存の CustomTkinter アプリに組み込む場合は ``master=`` に root を渡す
（その場合 :meth:`run` は呼ばず ``show()`` だけ使う）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional, Union

import customtkinter as ctk

from . import geometry, theme
from .chips import Chip
from .theme import ColorSpec

log = logging.getLogger(__name__)

Dock = str            # "taskbar" | "float"
Renderer = Callable[[ctk.CTkFrame], None]


class TaskbarWidget:
    """タスクバーに追従する（または好きな位置に浮かぶ）小さなウィジェット窓。

    Args:
        title: float モードのヘッダに出すタイトル。
        dock: "taskbar"（追従・既定）か "float"（任意位置）。
        appearance: "system"/"light"/"dark"。外観モードを設定する。
        opacity: 窓の不透明度 0..1。
        gap: taskbar モードでトレイ左端から空ける余白(px)。
        follow_ms: taskbar 追従の間隔(ms)。
        taskbar_bg/taskbar_fg: taskbar モードの地色/文字色。既定の
            taskbar_bg="transparent" は地の箱を透明化し、文字だけがタスクバー上に
            乗る（最も馴染む）。"auto" でシステムのライト/ダークに合わせた不透明地、
            色を直接指定することもできる。
        state_file: float 位置を記憶するファイルパス（省略で記憶しない）。
        on_close: ヘッダの ✕ を押した時のコールバック（既定は hide）。
        master: 既存アプリへ組み込む時の root。省略時は自前の root を作る。
    """

    def __init__(self, *, title: str = "Widget", dock: Dock = "taskbar",
                 appearance: str = "system", opacity: float = 0.97,
                 gap: int = 16, offset_y: int = 0, follow_ms: int = 1200,
                 taskbar_bg: Union[str, None] = "transparent",
                 taskbar_fg: Union[str, None] = "auto",
                 state_file: Union[str, Path, None] = None,
                 on_close: Optional[Callable[[], None]] = None,
                 master: Optional[ctk.CTk] = None):
        self.title = title
        self._dock: Dock = dock
        self._opacity = opacity
        self._gap = gap
        self._default_gap = gap
        self._offset_y = offset_y          # taskbar: 中央からの縦ずらし量(px, 上が負)
        self._default_offset_y = offset_y
        self._follow_ms = follow_ms
        self._state_file = Path(state_file) if state_file else None
        self._on_close = on_close or self.hide

        if appearance in ("system", "light", "dark"):
            ctk.set_appearance_mode(appearance)

        self._transparent = (taskbar_bg == "transparent")
        self._tb_bg, self._tb_fg = self._resolve_taskbar_colors(taskbar_bg, taskbar_fg)

        self._owns_root = master is None
        self._root = master or ctk.CTk()
        if self._owns_root:
            self._root.withdraw()  # 可視なのはウィジェット窓(Toplevel)だけ

        self._chips: list[Chip] = []
        self._renderer: Optional[Renderer] = None
        self._empty_hint = "⚙ 項目が未設定です"
        self._timers: list[tuple[int, Callable[[], None]]] = []
        self._visible = False
        self._follow_job: Optional[str] = None
        self._drag = (0, 0)
        self._drag_origin = (0, 0)
        self._dragging = False       # 閾値を超えて実際に動かし始めたか
        self._last_geom: Optional[str] = None  # 直近に適用した geometry（重複適用の抑止）
        self._pos: Optional[dict] = None
        self._load_state()

        self._build_window()

    # ================= 窓の骨組み =================
    def _build_window(self) -> None:
        self.win = ctk.CTkToplevel(self._root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", float(self._opacity))
        except Exception:
            pass

        # ヘッダ（float モードのみ表示）
        self._header = ctk.CTkFrame(self.win, fg_color=theme.CARD_ALT,
                                    corner_radius=0, height=26)
        self._title = ctk.CTkLabel(self._header, text=self.title,
                                   font=theme.font(10, "bold"), text_color=theme.MUTED)
        self._title.pack(side="left", padx=10)
        ctk.CTkButton(self._header, text="✕", width=20, height=20, corner_radius=6,
                      fg_color="transparent", hover_color=theme.INSET,
                      text_color=theme.MUTED, font=theme.font(11),
                      command=lambda: self._on_close()).pack(side="right", padx=(0, 4))

        self._body = ctk.CTkFrame(self.win, fg_color="transparent")

        for w in (self._header, self._title):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

    # 透明化に使うキー色（この色のピクセルが透明になる。まず使われない暗色）。
    _TRANSPARENT_KEY = "#010101"

    def _resolve_taskbar_colors(self, bg, fg) -> tuple[str, str]:
        light = geometry.system_uses_light_theme()
        auto_fg = theme.TASKBAR_FG_LIGHT if light else theme.TASKBAR_FG_DARK
        if bg == "transparent":
            # 地は透明。文字は実際のタスクバー上で見えるよう明色寄りにする。
            return self._TRANSPARENT_KEY, (fg if fg not in (None, "auto") else auto_fg)
        auto_bg = theme.TASKBAR_BG_LIGHT if light else theme.TASKBAR_BG_DARK
        return (auto_bg if bg in (None, "auto") else bg,
                auto_fg if fg in (None, "auto") else fg)

    # ================= 内容 =================
    def chip(self, label: str = "", value: str = "", **kw) -> Chip:
        """テキストチップを追加して handle を返す。"""
        c = Chip(label, value, **kw)
        self._chips.append(c)
        if self._visible:
            self._relayout()
        return c

    def gauge(self, label: str = "", value: str = "", *, frac: float = 0.0,
              **kw) -> Chip:
        """セグメントバー付きチップ（float で映える）を追加して handle を返す。"""
        kw.setdefault("show_bar", True)
        return self.chip(label, value, frac=frac, **kw)

    def clear(self) -> None:
        """全チップを削除する。"""
        self._chips.clear()
        if self._visible:
            self._relayout()

    def renderer(self, fn: Renderer) -> Renderer:
        """本体の描画を完全に自前で行うコールバックを登録（チップより優先）。

        デコレータとしても使える。``fn(body_frame)`` が毎レイアウト時に呼ばれる。
        """
        self._renderer = fn
        if self._visible:
            self._relayout()
        return fn

    def empty_hint(self, text: str) -> None:
        """項目も renderer も無い時に出す案内文。"""
        self._empty_hint = text

    def refresh(self) -> None:
        """本体の中身を組み直す。renderer 利用時の再描画に使う
        （チップ利用時は ``chip.update()`` だけで十分なので通常は不要）。"""
        if self._visible:
            self._relayout()

    # ================= タイマー =================
    def every(self, ms: int):
        """``ms`` ミリ秒ごとに呼ぶコールバックを登録するデコレータ。"""
        def deco(fn: Callable[[], None]) -> Callable[[], None]:
            self._timers.append((ms, fn))
            if self._visible:
                self._schedule(ms, fn)
            return fn
        return deco

    def after(self, ms: int, fn: Callable[[], None]) -> str:
        return self.win.after(ms, fn)

    def _schedule(self, ms: int, fn: Callable[[], None]) -> None:
        def run():
            try:
                fn()
            except Exception:
                log.exception("every() コールバックで例外")
            if self._visible:
                self.win.after(ms, run)
        self.win.after(ms, run)

    # ================= 表示制御 =================
    @property
    def dock(self) -> Dock:
        return self._dock

    def set_dock(self, dock: Dock) -> None:
        self._dock = dock
        if self._visible:
            self.show()

    def show(self) -> None:
        self._layout_frame()
        self._relayout()
        self.win.update_idletasks()
        if self._dock == "taskbar" and geometry.find_taskbar():
            self._position_taskbar()
            self._start_follow()
        else:
            self._position_float()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        if not self._visible:
            for ms, fn in self._timers:
                self._schedule(ms, fn)
        self._visible = True

    def hide(self) -> None:
        self._stop_follow()
        self.win.withdraw()
        self._visible = False

    def toggle(self) -> None:
        self.hide() if self._visible else self.show()

    def run(self) -> None:
        """自前 root を持つ場合のみ: 表示してメインループに入る。"""
        if not self._owns_root:
            raise RuntimeError("master を渡した場合は run() ではなく show() を使ってください")
        self.show()
        self._root.mainloop()

    # ================= レイアウト =================
    def _layout_frame(self) -> None:
        """配置モードに応じてヘッダ表示/地色/余白を切り替える。"""
        self._body.pack_forget()
        self._header.pack_forget()
        if self._dock == "taskbar":
            self.win.configure(fg_color=self._tb_bg)
            # 透明化: 地色のピクセルを透明にし、文字だけをタスクバー上に乗せる。
            self._set_transparent(self._transparent)
            self._body.pack(fill="both", expand=True, padx=10, pady=0)
        else:
            self._header.pack(fill="x")
            self._set_transparent(False)  # float ではカード地を見せる
            self.win.configure(fg_color=theme.CARD)
            self._body.pack(fill="both", expand=True, padx=12, pady=(8, 10))

    def _set_transparent(self, on: bool) -> None:
        try:
            self.win.attributes("-transparentcolor",
                                self._TRANSPARENT_KEY if on else "")
        except Exception:
            pass

    def _relayout(self) -> None:
        """本体の中身（チップ or renderer）を組み直す。"""
        for c in self._body.winfo_children():
            c.destroy()

        if self._renderer is not None:
            self._renderer(self._body)
        elif not self._chips:
            fg = self._tb_fg if self._dock == "taskbar" else theme.MUTED
            ctk.CTkLabel(self._body, text=self._empty_hint, font=theme.font(11),
                         text_color=fg).pack(padx=4, pady=6)
        elif self._dock == "taskbar":
            self._render_row()
        else:
            self._render_stack()

        self._bind_drag_recursive(self._body)
        if self._dock == "taskbar" and self._visible:
            self.win.after(1, self._position_taskbar)

    def _render_row(self) -> None:
        """taskbar: チップを横一列に（細い区切り線つき）で並べ、縦中央寄せ。"""
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(expand=True)
        for i, chip in enumerate(self._chips):
            if i > 0:
                ctk.CTkFrame(row, width=1, height=22, fg_color=theme.resolve(theme.BORDER)
                             ).pack(side="left", padx=10)
            chip.build(row, "taskbar", self._tb_fg).pack(side="left")

    def _render_stack(self) -> None:
        """float: チップを縦に積む。"""
        for chip in self._chips:
            chip.build(self._body, "float", theme.TEXT).pack(fill="x", pady=3)

    # ================= 位置決め =================
    def _apply_geometry(self, spec: str) -> bool:
        """geometry を適用する。前回と同じなら何もしない（無駄な再描画＝ちらつき防止）。

        戻り値は実際に変更したか。
        """
        if spec == self._last_geom:
            return False
        self.win.geometry(spec)
        self._last_geom = spec
        return True

    def _position_float(self) -> None:
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        if self._pos:
            x, y = int(self._pos["x"]), int(self._pos["y"])
        else:
            left, top, right, bottom = geometry.work_area()
            x, y = right - w - 16, bottom - h - 16
        self._apply_geometry(f"{w}x{h}+{x}+{y}")

    def _position_taskbar(self) -> bool:
        g = geometry.find_taskbar()
        if not g or not g.horizontal:
            # 縦置き/自動非表示などで追従できない時は float で右下へ。
            self._position_float()
            return False
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        tb_h = g.height
        # バーより背が高いと浮いて見えるので、必ずバー高さ内にクランプする。
        h = min(self.win.winfo_reqheight(), tb_h)
        x, y = self._taskbar_xy(g, w, h)
        return self._apply_geometry(f"{w}x{h}+{x}+{y}")

    def _taskbar_xy(self, g: geometry.TaskbarInfo, w: int, h: int) -> tuple[int, int]:
        """トレイ左端から gap だけ離し、offset_y で縦をずらした位置（バー内にクランプ）。"""
        x = g.tray_left - w - self._gap
        x = max(g.left + 4, min(x, g.tray_left - w - 2))
        y = g.top + max(0, (g.height - h) // 2) + self._offset_y
        y = max(0, min(y, g.bottom - h))  # 画面外へ出さない
        return x, y

    def _start_follow(self) -> None:
        self._stop_follow()
        self._follow_job = self.win.after(self._follow_ms, self._follow_tick)

    def _stop_follow(self) -> None:
        if self._follow_job is not None:
            try:
                self.win.after_cancel(self._follow_job)
            except Exception:
                pass
            self._follow_job = None

    def _follow_tick(self) -> None:
        if self._visible and self._dock == "taskbar":
            # 位置が変わった時だけ前面化を再適用する（毎回やると微妙にちらつく）。
            if self._position_taskbar():
                self.win.lift()
                self.win.attributes("-topmost", True)
            self._follow_job = self.win.after(self._follow_ms, self._follow_tick)

    # ================= ドラッグ移動 =================
    # float: 自由位置を記憶。taskbar: 横だけ動かせてトレイからの間隔を記憶（追従は維持）。
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
        ny = e.y_root - self._drag[1]
        if self._dock == "taskbar":
            g = geometry.find_taskbar()
            if g and g.horizontal:
                w = self.win.winfo_reqwidth()
                h = min(self.win.winfo_reqheight(), g.height)
                nx = max(g.left + 4, min(nx, g.tray_left - w - 2))
                ny = max(0, min(ny, g.bottom - h))  # 縦もずらせる（画面内に限定）
                self.win.geometry(f"+{nx}+{ny}")
                return
        self.win.geometry(f"+{nx}+{ny}")

    def _drag_end(self, _e):
        if not self._dragging:
            return  # 動かしていない＝ただのクリック。再配置も保存もしない。
        self._dragging = False
        if self._dock == "taskbar":
            g = geometry.find_taskbar()
            if g and g.horizontal:
                w = self.win.winfo_reqwidth()
                h = min(self.win.winfo_reqheight(), g.height)
                self._gap = max(0, g.tray_left - (self.win.winfo_x() + w))
                center = g.top + max(0, (g.height - h) // 2)
                self._offset_y = self.win.winfo_y() - center
                self._last_geom = None  # ドラッグ後は追従計算を一度通す
                self._save_pos()
            return
        self._pos = {"x": self.win.winfo_x(), "y": self.win.winfo_y()}
        self._last_geom = None
        self._save_pos()

    # ================= 座標の調整（API）=================
    def set_gap(self, px: int) -> None:
        """taskbar: トレイ左端からの横間隔(px)を設定する。"""
        self._gap = max(0, int(px))
        self._save_pos()
        self._reposition()

    def set_offset_y(self, px: int) -> None:
        """taskbar: バー中央からの縦ずらし量(px, 上がマイナス)を設定する。"""
        self._offset_y = int(px)
        self._save_pos()
        self._reposition()

    def move_to(self, x: int, y: int) -> None:
        """float: ウィンドウ左上の絶対座標を設定する。"""
        self._pos = {"x": int(x), "y": int(y)}
        self._save_pos()
        self._reposition()

    def nudge(self, dx: int = 0, dy: int = 0) -> None:
        """現在のモードで相対的に微調整する（right/down が +）。

        taskbar では dx>0 がトレイへ近づく向き（gap を縮める）、dy>0 が下へ。
        float では単純にウィンドウを dx, dy だけ動かす。
        """
        if self._dock == "taskbar":
            self.set_gap(self._gap - dx)
            if dy:
                self.set_offset_y(self._offset_y + dy)
        else:
            self.win.update_idletasks()
            self.move_to(self.win.winfo_x() + dx, self.win.winfo_y() + dy)

    def _reposition(self) -> None:
        if not self._visible:
            return
        if self._dock == "taskbar":
            self._position_taskbar()
        else:
            self._position_float()

    def reset_position(self) -> None:
        """記憶した座標（float 位置・taskbar の間隔/縦ずらし）を既定へ戻す。"""
        self._pos = None
        self._gap = self._default_gap
        self._offset_y = self._default_offset_y
        self._save_pos()
        if self._visible:
            self.show()

    def _bind_drag_recursive(self, widget) -> None:
        try:
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_drag_recursive(child)

    # ================= 位置の永続化（float 位置と taskbar の間隔）=================
    def _load_state(self) -> None:
        if not self._state_file or not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            pos = data.get("pos")
            if pos and "x" in pos and "y" in pos:
                self._pos = pos
            if isinstance(data.get("gap"), (int, float)):
                self._gap = int(data["gap"])
            if isinstance(data.get("offset_y"), (int, float)):
                self._offset_y = int(data["offset_y"])
        except Exception:
            pass

    def _save_pos(self) -> None:
        if not self._state_file:
            return
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(
                json.dumps({"pos": self._pos, "gap": self._gap,
                            "offset_y": self._offset_y}), encoding="utf-8")
        except Exception:
            log.debug("位置の保存に失敗")
