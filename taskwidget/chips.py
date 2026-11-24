"""ウィジェットに載せる最小の表示部品「チップ」.

チップは「ラベル＋値（＋任意のセグメントバー）」の一塊。配置モードに応じて
見え方が変わる:

* taskbar: ラベル(小)を上、値(大)を下に積む縦スタック。省スペースで視認性重視。
* float  : ラベル左・値右の横並び（任意でバーを中央に）。カード上に落ち着いて並ぶ。

値の更新は :meth:`Chip.refresh` が既存ラベルを ``configure`` し直すだけなので
（毎回ウィジェットを作り直さない）、チラつかず軽い。構造が変わる追加/削除や
配置モード切替のときだけ親側が :meth:`Chip.build` で組み直す。
"""
from __future__ import annotations

from typing import Optional

import customtkinter as ctk

from . import theme
from .theme import ColorSpec


class Chip:
    """1項目を表す表示部品。``TaskbarWidget.chip()`` 等で生成して扱う。"""

    def __init__(self, label: str = "", value: str = "", *,
                 status: Optional[str] = None, color: Optional[ColorSpec] = None,
                 frac: Optional[float] = None, show_bar: bool = False):
        self.label = label
        self.value = value
        self.status = status           # "ok"/"warn"/"critical"/"stale"/"info"
        self.color = color             # 明示色（status より優先）
        self.frac = frac               # 0..1。バー表示に使う
        self.show_bar = show_bar

        self._root: Optional[ctk.CTkBaseClass] = None
        self._lbl: Optional[ctk.CTkLabel] = None
        self._val: Optional[ctk.CTkLabel] = None
        self._dot: Optional[ctk.CTkFrame] = None
        self._bar_cell: Optional[ctk.CTkFrame] = None
        self._dock = "float"
        self._fg: ColorSpec = theme.TEXT
        self._on_change = None  # 親へ「再レイアウトして」と伝える（任意）

    # ---- 公開 API ----
    def update(self, *, label: Optional[str] = None, value: Optional[str] = None,
               status: Optional[str] = "\0", color: Optional[ColorSpec] = "\0",
               frac: Optional[float] = "\0") -> "Chip":
        """表示内容を更新する。指定した引数だけ反映（他は維持）。

        ``status``/``color``/``frac`` は None を「明示的に消す」意味で使えるよう、
        センチネル("\\0")で「未指定」と区別する。
        """
        if label is not None:
            self.label = label
        if value is not None:
            self.value = value
        if status != "\0":
            self.status = status
        if color != "\0":
            self.color = color
        if frac != "\0":
            self.frac = frac
        self.refresh()
        return self

    # ---- 値色の決定 ----
    def _value_color(self) -> ColorSpec:
        if self.color is not None:
            return self.color
        if self.status:
            return theme.status_color(self.status, default=self._fg)
        return self._fg

    def _bar_color(self) -> str:
        if isinstance(self.color, str):
            return self.color
        if self.status:
            return theme.STATUS_COLOR.get(self.status, theme.resolve(theme.ACCENT))
        return theme.resolve(theme.ACCENT)

    # ---- 構築（構造が変わる時だけ呼ぶ）----
    def build(self, parent, dock: str, fg: ColorSpec) -> ctk.CTkBaseClass:
        self._dock = dock
        self._fg = fg
        # 旧モードのウィジェット参照は破棄済みなのでクリア（stale 参照の configure 防止）。
        self._lbl = self._val = self._dot = self._bar_cell = None
        root = ctk.CTkFrame(parent, fg_color="transparent")
        self._root = root
        if dock == "taskbar":
            self._build_taskbar(root)
        else:
            self._build_float(root)
        self.refresh()
        return root

    def _build_taskbar(self, root) -> None:
        # ラベル(小・淡色) を上、値(大・太字) を下へ。状態はドットで色付け。
        head = ctk.CTkFrame(root, fg_color="transparent")
        head.pack(anchor="center")
        self._dot = ctk.CTkFrame(head, width=6, height=6, corner_radius=3,
                                 fg_color="transparent")
        self._dot.pack(side="left", padx=(0, 4))
        self._lbl = ctk.CTkLabel(head, text=self.label, font=theme.font(9),
                                 height=14, text_color=self._fg)
        self._lbl.pack(side="left")
        self._val = ctk.CTkLabel(root, text=self.value, font=theme.font(14, "bold"),
                                 height=20)
        self._val.pack(anchor="center")

    def _build_float(self, root) -> None:
        # ラベル左・値右。任意でセグメントバーを中央に。
        self._lbl = ctk.CTkLabel(root, text=self.label, font=theme.font(12),
                                 text_color=theme.MUTED, anchor="w")
        self._lbl.pack(side="left")
        self._val = ctk.CTkLabel(root, text=self.value, font=theme.font(13, "bold"),
                                 anchor="e")
        self._val.pack(side="right", padx=(12, 0))
        if self.show_bar:
            self._bar_cell = ctk.CTkFrame(root, fg_color="transparent")
            self._bar_cell.pack(side="right", padx=(10, 0))

    # ---- 更新（既存ウィジェットを configure）----
    def refresh(self) -> None:
        if self._val is None:  # 未構築
            return
        self._val.configure(text=self.value or "--", text_color=self._value_color())
        if self._lbl is not None:
            self._lbl.configure(text=self.label)
        if self._dot is not None:
            on = bool(self.status and self.status != "ok")
            self._dot.configure(fg_color=self._bar_color() if on else "transparent")
        if self.show_bar and self._bar_cell is not None:
            for c in self._bar_cell.winfo_children():
                c.destroy()
            frac = 0.0 if self.frac is None else self.frac
            surface = theme.CARD
            bar = theme.make_segbar(self._bar_cell, frac, self._bar_color(),
                                    surface=surface, width=90)
            bar.pack()
