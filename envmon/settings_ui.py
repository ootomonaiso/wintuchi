"""設定画面（全般 / 部屋 / ウィジェット の3タブ構成）.

- 部屋はタブを増やさず、ドロップダウンで切り替える。
- しきい値・状態の呼び方には「プリセット」をワンクリックで流し込める。
- ラベルは専門用語を避け、補足説明を添える。見た目は theme.py に一元化。
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

from . import presets, startup, theme
from .config import DEFAULT_ROOM, Config, _deep_merge
from .model import AppState, Severity

log = logging.getLogger(__name__)

_METRICS = [("temp", "気温", "℃"), ("humid", "湿度", "%"), ("lux", "照度", "lx")]
_METRIC_LABEL = {k: lbl for k, lbl, _u in _METRICS}


def _num(entry_val: str, default=None, is_int=False):
    s = (entry_val or "").strip()
    if s == "":
        return None
    try:
        return int(float(s)) if is_int else float(s)
    except ValueError:
        return default


def _hint(parent, text: str) -> None:
    """薄字の補足説明を1行置く。"""
    ctk.CTkLabel(parent, text=text, font=theme.font(10),
                 text_color=theme.FAINT, anchor="w", justify="left").pack(anchor="w", pady=(0, 2))


def _section(parent, title: str) -> None:
    """アクセントバー付きのセクション見出し。"""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(anchor="w", fill="x", pady=(16, 4))
    ctk.CTkFrame(row, width=3, height=15, corner_radius=2,
                 fg_color=theme.ACCENT).pack(side="left", padx=(0, 7))
    ctk.CTkLabel(row, text=title, font=theme.font(13, "bold"),
                 text_color=theme.TEXT, anchor="w").pack(side="left")


def _card(parent) -> ctk.CTkFrame:
    """内容をまとめる薄いカード。"""
    c = ctk.CTkFrame(parent, fg_color=theme.CARD_ALT, corner_radius=theme.R_CARD,
                     border_width=1, border_color=theme.BORDER)
    c.pack(fill="x", pady=2)
    inner = ctk.CTkFrame(c, fg_color="transparent")
    inner.pack(fill="x", padx=12, pady=10)
    return inner


class SettingsWindow:
    """モーダルではない設定ウィンドウ（単一インスタンス）."""

    def __init__(self, master, config: Config, state: AppState, notifier,
                 on_saved: Callable[[], None]):
        self.config = config
        self.state = state
        self.notifier = notifier
        self.on_saved = on_saved
        self.master = master
        self.win: Optional[ctk.CTkToplevel] = None
        self._room_vars: dict[str, dict] = {}
        self._room_frames: dict[str, ctk.CTkFrame] = {}
        self._sensor_room_vars: dict[str, tk.StringVar] = {}
        self._w_items: list[tuple[str, str]] = []

    def open(self, focus_room: Optional[str] = None) -> None:
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            if focus_room:
                self.tabs.set("部屋")
                self._show_room(focus_room)
            return
        self._build(focus_room)

    def _known_rooms(self) -> list[str]:
        cfg = self.config.snapshot()
        rooms = set(cfg.get("rooms", {}))
        rooms |= set(cfg.get("sensors", {}).values())
        with self.state.lock:
            rooms |= set(self.state.rooms)
        return sorted(rooms)

    def _build(self, focus_room: Optional[str]) -> None:
        cfg = self.config.snapshot()
        self.win = ctk.CTkToplevel(self.master)
        self.win.title("環境モニタ — 設定")
        self.win.geometry("640x710")
        self.win.configure(fg_color=theme.WINDOW)
        self.win.attributes("-topmost", True)
        self.win.after(300, lambda: self.win.attributes("-topmost", False))

        self.tabs = ctk.CTkTabview(self.win, fg_color=theme.CARD,
                                   segmented_button_selected_color=theme.ACCENT,
                                   segmented_button_selected_hover_color=theme.ACCENT_HOVER)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        self._build_general_tab(self.tabs.add("全般"), cfg)
        self._build_rooms_tab(self.tabs.add("部屋"), cfg)
        self._build_widget_tab(self.tabs.add("ウィジェット"), cfg)

        bar = ctk.CTkFrame(self.win, fg_color="transparent")
        bar.pack(fill="x", padx=12, pady=(2, 10))
        ctk.CTkButton(bar, text="保存して閉じる", width=140, height=34,
                      corner_radius=theme.R_INPUT, font=theme.font(12, "bold"),
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._save).pack(side="right", padx=(6, 0))
        ctk.CTkButton(bar, text="閉じる", width=84, height=34,
                      corner_radius=theme.R_INPUT, fg_color="transparent",
                      hover_color=theme.INSET, text_color=theme.MUTED,
                      border_width=1, border_color=theme.BORDER,
                      command=self._close).pack(side="right")
        ctk.CTkButton(bar, text="🔔 お試し通知", width=120, height=34,
                      corner_radius=theme.R_INPUT, fg_color="transparent",
                      hover_color=theme.INSET, text_color=theme.ACCENT,
                      border_width=1, border_color=theme.BORDER,
                      command=self._test_notify).pack(side="left")

        if focus_room:
            self.tabs.set("部屋")
            self._show_room(focus_room)

    # ========================= 全般タブ =========================
    def _build_general_tab(self, parent, cfg: dict) -> None:
        f = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        f.pack(fill="both", expand=True)
        self._g = {}

        def field(parent_, label, key, value, hint="", width=360):
            ctk.CTkLabel(parent_, text=label, anchor="w", text_color=theme.TEXT,
                         font=theme.font(12)).pack(anchor="w", pady=(6, 0))
            if hint:
                _hint(parent_, hint)
            var = tk.StringVar(value="" if value is None else str(value))
            ctk.CTkEntry(parent_, textvariable=var, width=width, height=32,
                         corner_radius=theme.R_INPUT, border_color=theme.BORDER,
                         fg_color=theme.INSET).pack(anchor="w")
            self._g[key] = var

        # --- 現在の接続状態バナー（いま動いているか一目で分かるように）---
        self._status_banner = ctk.CTkFrame(f, corner_radius=theme.R_CARD,
                                           border_width=1, border_color=theme.BORDER)
        self._status_banner.pack(fill="x", pady=(0, 2))
        self._status_dot = ctk.CTkLabel(self._status_banner, text="●", width=16,
                                        font=theme.font(13))
        self._status_dot.pack(side="left", padx=(12, 6), pady=9)
        self._status_text = ctk.CTkLabel(self._status_banner, text="", anchor="w",
                                         font=theme.font(12), justify="left")
        self._status_text.pack(side="left", pady=9)
        self._refresh_status_banner()

        _section(f, "接続")
        c = _card(f)
        field(c, "環境モニタの URL", "url", cfg.get("url"),
              "例: http://192.168.1.10/env1.php")
        # 保存前に URL を試せる接続テスト
        tr = ctk.CTkFrame(c, fg_color="transparent")
        tr.pack(fill="x", pady=(4, 2))
        ctk.CTkButton(tr, text="接続テスト", width=96, height=28, corner_radius=theme.R_INPUT,
                      fg_color="transparent", hover_color=theme.INSET, text_color=theme.ACCENT,
                      border_width=1, border_color=theme.BORDER,
                      command=self._test_connection).pack(side="left")
        self._conn_result = ctk.CTkLabel(tr, text="URL を入れて「接続テスト」で確認できます",
                                         font=theme.font(11), text_color=theme.FAINT, anchor="w")
        self._conn_result.pack(side="left", padx=(10, 0))
        field(c, "取得間隔（秒）", "poll_interval_sec", cfg.get("poll_interval_sec"),
              "何秒ごとに値を取りに行くか", width=120)
        field(c, "通信タイムアウト（秒）", "request_timeout_sec", cfg.get("request_timeout_sec"),
              "応答を待つ上限", width=120)

        _section(f, "通知")
        c = _card(f)
        field(c, "Teams 通知用 URL（Power Automate）", "teams_webhook_url",
              cfg.get("teams_webhook_url"), "空欄なら Teams へは送りません")
        field(c, "同じ通知を再送しない時間（分）", "cooldown_minutes", cfg.get("cooldown_minutes"),
              "一度通知したら、この時間は同じ通知を出しません（連続通知の抑制）", width=120)
        field(c, "無応答を「応答なし」とみなす時間（分）", "stale_minutes", cfg.get("stale_minutes"),
              "この時間データが届かないセンサを知らせます", width=120)

        qh = cfg.get("quiet_hours", {})
        ctk.CTkLabel(c, text="通知しない時間帯（静音）", anchor="w", text_color=theme.TEXT,
                     font=theme.font(12)).pack(anchor="w", pady=(8, 0))
        _hint(c, "夜間など、ここで指定した時間帯はトースト/Teams を出しません")
        qf = ctk.CTkFrame(c, fg_color="transparent")
        qf.pack(anchor="w")
        self._g["quiet_enabled"] = tk.BooleanVar(value=qh.get("enabled", False))
        ctk.CTkSwitch(qf, text="使う", variable=self._g["quiet_enabled"]).pack(side="left")
        self._g["quiet_start"] = tk.StringVar(value=qh.get("start", "22:00"))
        self._g["quiet_end"] = tk.StringVar(value=qh.get("end", "07:00"))
        ctk.CTkEntry(qf, textvariable=self._g["quiet_start"], width=66, height=30,
                     corner_radius=theme.R_INPUT, fg_color=theme.INSET,
                     border_color=theme.BORDER).pack(side="left", padx=(10, 2))
        ctk.CTkLabel(qf, text="〜").pack(side="left")
        ctk.CTkEntry(qf, textvariable=self._g["quiet_end"], width=66, height=30,
                     corner_radius=theme.R_INPUT, fg_color=theme.INSET,
                     border_color=theme.BORDER).pack(side="left", padx=2)

        # --- 状態の呼び方（カスタム + プリセット）---
        _section(f, "状態の呼び方")
        c = _card(f)
        _hint(c, "「異常」のような強い言葉がしっくりこないときは、好きな言葉へ。"
                 "ここで決めた名前が画面と Teams 通知に出ます。")
        pr = ctk.CTkFrame(c, fg_color="transparent")
        pr.pack(fill="x", pady=(2, 6))
        ctk.CTkLabel(pr, text="プリセット", width=70, anchor="w",
                     text_color=theme.MUTED, font=theme.font(11)).pack(side="left")
        self._label_preset = tk.StringVar(value=presets.LABEL_PRESET_PLACEHOLDER)
        ctk.CTkOptionMenu(
            pr, values=list(presets.LABEL_PRESETS.keys()), variable=self._label_preset,
            width=180, fg_color=theme.INSET, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT,
            command=self._apply_label_preset).pack(side="left")

        labels = cfg.get("labels", {}) or {}
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.pack(fill="x")
        defs = [("ok", "正常のとき", presets.DEFAULT_LABELS["ok"]),
                ("warn", "軽い通知", presets.DEFAULT_LABELS["warn"]),
                ("critical", "強めの通知", presets.DEFAULT_LABELS["critical"]),
                ("stale", "応答なし", presets.DEFAULT_LABELS["stale"])]
        for i, (key, cap, dflt) in enumerate(defs):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=i // 2, column=i % 2, padx=(0, 16), pady=3, sticky="w")
            ctk.CTkLabel(cell, text=cap, width=72, anchor="w",
                         text_color=theme.MUTED, font=theme.font(11)).pack(side="left")
            var = tk.StringVar(value=str(labels.get(key, dflt)))
            ctk.CTkEntry(cell, textvariable=var, width=120, height=30,
                         corner_radius=theme.R_INPUT, fg_color=theme.INSET,
                         border_color=theme.BORDER).pack(side="left")
            self._g[f"label_{key}"] = var

        _section(f, "起動")
        c = _card(f)
        self._g["run_at_startup"] = tk.BooleanVar(value=startup.is_registered())
        ctk.CTkSwitch(c, text="Windows にログインしたら自動で起動する",
                      variable=self._g["run_at_startup"]).pack(anchor="w", pady=2)

        _section(f, "センサと部屋の対応")
        c = _card(f)
        _hint(c, "対応表 sensors.json はあなたが用意・編集するファイルです。"
                 "アプリは読むだけで書き換えません。外部で編集すると次のポーリングで自動反映されます。")
        btns = ctk.CTkFrame(c, fg_color="transparent")
        btns.pack(fill="x", pady=(2, 6))
        _ghost = dict(corner_radius=theme.R_INPUT, height=28, fg_color="transparent",
                      hover_color=theme.INSET, text_color=theme.ACCENT,
                      border_width=1, border_color=theme.BORDER)
        ctk.CTkButton(btns, text="sensors.json のフォルダを開く", width=200,
                      command=self._open_sensors_folder, **_ghost).pack(side="left")
        # 現在読み込まれている対応表を読み取り専用で表示（編集はJSONで行う）
        self._sensor_section = ctk.CTkFrame(c, fg_color="transparent")
        self._sensor_section.pack(fill="x")
        self._render_sensor_rows(self._collect_known_sensors(cfg))

    def _apply_label_preset(self, name: str) -> None:
        data = presets.LABEL_PRESETS.get(name)
        if not data:
            return
        for key, val in data.items():
            var = self._g.get(f"label_{key}")
            if var is not None:
                var.set(val)

    # --- 接続状態バナー / 接続テスト ---
    def _refresh_status_banner(self) -> None:
        with self.state.lock:
            last_ok = self.state.last_poll_ok
            last_err = self.state.last_poll_error
            n_rooms = len(self.state.rooms)
        if last_err:
            sev, msg = Severity.CRITICAL, f"つながっていません（{str(last_err)[:36]}）"
        elif last_ok:
            sev = Severity.OK
            msg = f"接続中 — 最終取得 {last_ok.strftime('%H:%M:%S')} ／ {n_rooms} 部屋を監視中"
        else:
            sev, msg = Severity.STALE, "まだデータを取得していません（URL を確認してください）"
        self._status_banner.configure(fg_color=theme.SEV_SOFT[sev])
        self._status_dot.configure(text_color=theme.SEV_COLOR[sev])
        self._status_text.configure(text=msg, text_color=theme.SEV_TEXT[sev])

    def _test_connection(self) -> None:
        url = self._g["url"].get().strip()
        if not url:
            self._conn_result.configure(text="URL を入力してください",
                                        text_color=theme.SEV_TEXT[Severity.WARN])
            return
        self._conn_result.configure(text="接続中…", text_color=theme.MUTED)
        timeout = _num(self._g["request_timeout_sec"].get(), 5, is_int=True) or 5

        def work():
            from .poller import latest_per_sensor, parse_records
            try:
                import requests
                resp = requests.get(url, timeout=timeout)
                resp.raise_for_status()
                latest = latest_per_sensor(parse_records(resp.text))
                n = len(latest)
                if n:
                    msg, sev = f"✓ 接続OK — {n} 台のセンサを受信しました", Severity.OK
                else:
                    msg, sev = "△ つながりましたが、データが空でした", Severity.WARN
            except Exception as e:  # requests/parse いずれの失敗も拾う
                msg, sev = f"✕ つながりません（{str(e)[:40]}）", Severity.CRITICAL
            self._safe_after(lambda: self._conn_result.configure(
                text=msg, text_color=theme.SEV_TEXT[sev]))

        threading.Thread(target=work, name="conn-test", daemon=True).start()

    def _safe_after(self, fn) -> None:
        """別スレッドから UI 更新を安全にメインスレッドへ回す。"""
        try:
            if self.win is not None and self.win.winfo_exists():
                self.win.after(0, fn)
        except Exception:
            pass

    # ========================= 部屋タブ =========================
    def _build_rooms_tab(self, parent, cfg: dict) -> None:
        rooms = self._known_rooms()
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=4, pady=(6, 2))
        ctk.CTkLabel(top, text="部屋を選ぶ", anchor="w", text_color=theme.TEXT,
                     font=theme.font(12, "bold")).pack(side="left", padx=(0, 8))
        self._room_sel = tk.StringVar(value=rooms[0] if rooms else "")
        self._room_menu = ctk.CTkOptionMenu(
            top, values=rooms or ["（部屋なし）"], variable=self._room_sel,
            width=240, fg_color=theme.INSET, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT,
            command=self._show_room)
        self._room_menu.pack(side="left")
        _hint(parent, "ここで選んだ部屋のしきい値・通知設定を下で編集します。")

        self._rooms_container = ctk.CTkFrame(parent, fg_color="transparent")
        self._rooms_container.pack(fill="both", expand=True, padx=4)

        self._room_vars.clear()
        self._room_frames.clear()
        for room in rooms:
            self._room_frames[room] = self._make_room_frame(room, cfg)
        if rooms:
            self._show_room(rooms[0])
        else:
            ctk.CTkLabel(self._rooms_container,
                         text="まだ部屋がありません。\n"
                         "sensors.json にセンサID→部屋名を書くと、ここに部屋が並びます。\n"
                         "（「全般」タブの「センサと部屋の対応」からフォルダを開けます）",
                         text_color=theme.MUTED, justify="center").pack(pady=20)

    def _show_room(self, room: str) -> None:
        for fr in self._room_frames.values():
            fr.pack_forget()
        fr = self._room_frames.get(room)
        if fr is not None:
            fr.pack(fill="both", expand=True)
            self._room_sel.set(room)

    def _make_room_frame(self, room: str, cfg: dict) -> ctk.CTkFrame:
        rc = _deep_merge(DEFAULT_ROOM, cfg.get("rooms", {}).get(room, {}))
        f = ctk.CTkScrollableFrame(self._rooms_container, fg_color="transparent")
        v: dict = {}

        # プリセット流し込み
        _section(f, "しきい値（この範囲を外れたら通知）")
        c = _card(f)
        pr = ctk.CTkFrame(c, fg_color="transparent")
        pr.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(pr, text="プリセット", width=70, anchor="w",
                     text_color=theme.MUTED, font=theme.font(11)).pack(side="left")
        preset_sel = tk.StringVar(value=presets.ROOM_PRESET_PLACEHOLDER)
        preset_hint = ctk.CTkLabel(c, text="", font=theme.font(10),
                                   text_color=theme.FAINT, anchor="w", justify="left")
        ctk.CTkOptionMenu(
            pr, values=[n for n, _d in presets.ROOM_PRESETS], variable=preset_sel,
            width=260, fg_color=theme.INSET, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT,
            command=lambda name: self._apply_room_preset(v, name, preset_hint)).pack(side="left")
        preset_hint.pack(anchor="w", pady=(2, 4))
        _hint(c, "空欄にした項目はチェックしません（通知しません）。")

        def minmax(label, key):
            r = ctk.CTkFrame(c, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=label, width=96, anchor="w",
                         text_color=theme.TEXT, font=theme.font(12)).pack(side="left")
            ctk.CTkLabel(r, text="下限", text_color=theme.MUTED,
                         font=theme.font(11)).pack(side="left")
            lo = tk.StringVar(value="" if rc[key].get("min") is None else str(rc[key]["min"]))
            ctk.CTkEntry(r, textvariable=lo, width=72, height=30, corner_radius=theme.R_INPUT,
                         fg_color=theme.INSET, border_color=theme.BORDER).pack(side="left", padx=(4, 12))
            ctk.CTkLabel(r, text="上限", text_color=theme.MUTED,
                         font=theme.font(11)).pack(side="left")
            hi = tk.StringVar(value="" if rc[key].get("max") is None else str(rc[key]["max"]))
            ctk.CTkEntry(r, textvariable=hi, width=72, height=30, corner_radius=theme.R_INPUT,
                         fg_color=theme.INSET, border_color=theme.BORDER).pack(side="left", padx=4)
            v[key] = (lo, hi)

        minmax("気温（℃）", "temp")
        minmax("湿度（%）", "humid")

        _section(f, "明るさ（照度）による通知の制御")
        c = _card(f)
        _hint(c, "例：明るいときだけ通知＝在室中だけ知らせる／暗いときだけ通知＝消灯中を監視。")
        gr = ctk.CTkFrame(c, fg_color="transparent")
        gr.pack(fill="x", pady=3)
        mode_map = {"off": "いつでも通知する",
                    "above": "明るいときだけ通知（照度が指定以上）",
                    "below": "暗いときだけ通知（照度が指定以下）"}
        inv_mode = {disp: k for k, disp in mode_map.items()}
        gate_mode = tk.StringVar(value=mode_map.get(rc["lux_gate"]["mode"], "いつでも通知する"))
        ctk.CTkOptionMenu(gr, values=list(mode_map.values()), variable=gate_mode,
                          width=300, fg_color=theme.INSET, button_color=theme.ACCENT,
                          button_hover_color=theme.ACCENT_HOVER,
                          text_color=theme.TEXT).pack(side="left")
        g2 = ctk.CTkFrame(c, fg_color="transparent")
        g2.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(g2, text="境目の明るさ", text_color=theme.TEXT,
                     font=theme.font(12)).pack(side="left")
        gate_val = tk.StringVar(value=str(rc["lux_gate"].get("value", 50)))
        ctk.CTkEntry(g2, textvariable=gate_val, width=72, height=30, corner_radius=theme.R_INPUT,
                     fg_color=theme.INSET, border_color=theme.BORDER).pack(side="left", padx=6)
        ctk.CTkLabel(g2, text="lux", text_color=theme.MUTED).pack(side="left")
        v["lux_gate"] = (gate_mode, gate_val, inv_mode)

        _section(f, "この部屋の通知先")
        c = _card(f)
        ch = rc.get("channels", {})
        v["toast"] = tk.BooleanVar(value=ch.get("toast", True))
        v["teams"] = tk.BooleanVar(value=ch.get("teams", True))
        v["stale_enabled"] = tk.BooleanVar(value=rc.get("stale_enabled", True))
        ctk.CTkSwitch(c, text="Windows の通知（トースト）", variable=v["toast"]).pack(anchor="w", pady=3)
        ctk.CTkSwitch(c, text="Teams の通知", variable=v["teams"]).pack(anchor="w", pady=3)
        ctk.CTkSwitch(c, text="センサの応答なしを知らせる", variable=v["stale_enabled"]).pack(anchor="w", pady=3)

        self._room_vars[room] = v
        return f

    def _apply_room_preset(self, v: dict, name: str, hint_label) -> None:
        data = presets.room_preset(name)
        if not data:
            return
        for key in ("temp", "humid"):
            lo, hi = data.get(key, (None, None))
            lo_var, hi_var = v[key]
            lo_var.set("" if lo is None else f"{lo:g}")
            hi_var.set("" if hi is None else f"{hi:g}")
        hint_label.configure(text=data.get("hint", ""))

    # ========================= ウィジェットタブ =========================
    def _build_widget_tab(self, parent, cfg: dict) -> None:
        w = cfg.get("widget", {})
        f = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        f.pack(fill="both", expand=True)

        c = _card(f)
        self._w_enabled = tk.BooleanVar(value=w.get("enabled", False))
        ctk.CTkSwitch(c, text="デスクトップにウィジェットを表示する（常に最前面）",
                      variable=self._w_enabled).pack(anchor="w", pady=(2, 6))

        dr = ctk.CTkFrame(c, fg_color="transparent")
        dr.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(dr, text="置き場所", width=70, anchor="w", text_color=theme.TEXT,
                     font=theme.font(12)).pack(side="left")
        _dock_map = {"taskbar": "タスクバーの上に出す（追従）", "float": "好きな位置に置く"}
        self._w_dock_disp = tk.StringVar(
            value=_dock_map.get(w.get("dock", "taskbar"), "タスクバーの上に出す（追従）"))
        self._w_dock_inv = {val: k for k, val in _dock_map.items()}
        ctk.CTkOptionMenu(dr, values=list(_dock_map.values()), variable=self._w_dock_disp,
                          width=240, fg_color=theme.INSET, button_color=theme.ACCENT,
                          button_hover_color=theme.ACCENT_HOVER,
                          text_color=theme.TEXT).pack(side="left")
        _hint(c, "「タスクバーの上に出す」はシステムトレイの左隣に重ねてタスクバーに追従します。"
                 "どちらもドラッグで動かせ、トレイメニュー「ウィジェット位置をリセット」で既定位置へ戻せます。")

        _section(f, "表示する項目")
        c = _card(f)
        _hint(c, "下のリストの順番で表示されます。")
        self._w_items = [(it.get("room"), it.get("metric"))
                         for it in w.get("items", [])
                         if isinstance(it, dict) and it.get("metric") in _METRIC_LABEL]
        self._w_list = ctk.CTkFrame(c, fg_color="transparent")
        self._w_list.pack(fill="x", pady=(2, 6))
        self._render_widget_items()

        add = ctk.CTkFrame(c, fg_color=theme.INSET, corner_radius=theme.R_INPUT)
        add.pack(fill="x", pady=4)
        ctk.CTkLabel(add, text="追加:", text_color=theme.MUTED).pack(side="left", padx=(10, 4), pady=7)
        rooms = self._known_rooms() or ["（部屋なし）"]
        self._w_add_room = tk.StringVar(value=rooms[0])
        ctk.CTkOptionMenu(add, values=rooms, variable=self._w_add_room, width=150,
                          fg_color=theme.CARD, button_color=theme.ACCENT,
                          button_hover_color=theme.ACCENT_HOVER,
                          text_color=theme.TEXT).pack(side="left", padx=2)
        self._w_add_metric = tk.StringVar(value="気温")
        ctk.CTkOptionMenu(add, values=[lbl for _k, lbl, _u in _METRICS],
                          variable=self._w_add_metric, width=90, fg_color=theme.CARD,
                          button_color=theme.ACCENT, button_hover_color=theme.ACCENT_HOVER,
                          text_color=theme.TEXT).pack(side="left", padx=2)
        ctk.CTkButton(add, text="＋ 追加", width=72, height=28, corner_radius=theme.R_INPUT,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._add_widget_item).pack(side="left", padx=6)

    def _render_widget_items(self) -> None:
        for c in self._w_list.winfo_children():
            c.destroy()
        if not self._w_items:
            ctk.CTkLabel(self._w_list, text="（まだありません。下の「追加」から選んでください）",
                         text_color=theme.FAINT).pack(anchor="w", pady=4)
            return
        for idx, (room, metric) in enumerate(self._w_items):
            r = ctk.CTkFrame(self._w_list, fg_color=theme.CARD, corner_radius=theme.R_INPUT,
                             border_width=1, border_color=theme.BORDER)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=f"{room}　{_METRIC_LABEL.get(metric, metric)}",
                         anchor="w", text_color=theme.TEXT).pack(side="left", padx=12, pady=5)
            ctk.CTkButton(r, text="✕", width=28, height=24, corner_radius=6,
                          fg_color="transparent", hover_color=theme.INSET,
                          text_color=theme.SEV_TEXT[Severity.CRITICAL],
                          command=lambda i=idx: self._remove_widget_item(i)).pack(side="right", padx=(2, 6))
            ctk.CTkButton(r, text="↓", width=28, height=24, corner_radius=6,
                          fg_color="transparent", hover_color=theme.INSET, text_color=theme.MUTED,
                          command=lambda i=idx: self._move_widget_item(i, 1)).pack(side="right", padx=2)
            ctk.CTkButton(r, text="↑", width=28, height=24, corner_radius=6,
                          fg_color="transparent", hover_color=theme.INSET, text_color=theme.MUTED,
                          command=lambda i=idx: self._move_widget_item(i, -1)).pack(side="right", padx=2)

    def _add_widget_item(self) -> None:
        room = self._w_add_room.get()
        metric = {lbl: k for k, lbl, _u in _METRICS}.get(self._w_add_metric.get())
        if not room or room == "（部屋なし）" or not metric:
            return
        if (room, metric) in self._w_items:
            return
        self._w_items.append((room, metric))
        self._render_widget_items()

    def _remove_widget_item(self, idx: int) -> None:
        if 0 <= idx < len(self._w_items):
            self._w_items.pop(idx)
            self._render_widget_items()

    def _move_widget_item(self, idx: int, delta: int) -> None:
        j = idx + delta
        if 0 <= idx < len(self._w_items) and 0 <= j < len(self._w_items):
            self._w_items[idx], self._w_items[j] = self._w_items[j], self._w_items[idx]
            self._render_widget_items()

    # ========================= センサ対応（全般タブ内） =========================
    def _collect_known_sensors(self, cfg: dict) -> dict:
        sensors = dict(cfg.get("sensors", {}))
        with self.state.lock:
            for rs in self.state.rooms.values():
                for sid in rs.sensor_ids:
                    sensors.setdefault(str(sid), rs.name)
        return sensors

    def _render_sensor_rows(self, sensors: dict) -> None:
        """現在読み込まれている対応表を読み取り専用で一覧表示する（編集は JSON で）。"""
        for w in self._sensor_section.winfo_children():
            w.destroy()
        if not sensors:
            ctk.CTkLabel(self._sensor_section,
                         text="（sensors.json がまだありません。例: {\"1\": \"会議室A\"}）",
                         text_color=theme.FAINT).pack(anchor="w")
            return
        for sid in sorted(sensors, key=lambda x: int(x) if str(x).isdigit() else 0):
            r = ctk.CTkFrame(self._sensor_section, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=f"センサ {sid}", width=100, anchor="w",
                         text_color=theme.MUTED, font=theme.font(12)).pack(side="left")
            ctk.CTkLabel(r, text=f"→　{sensors[sid]}", anchor="w",
                         text_color=theme.TEXT, font=theme.font(12)).pack(side="left")

    def _open_sensors_folder(self) -> None:
        import os
        from .config import sensors_path
        try:
            os.startfile(str(sensors_path().parent))
        except OSError as e:
            log.error("フォルダを開けません: %s", e)

    # ========================= 保存 =========================
    def _collect(self) -> dict:
        cfg = self.config.snapshot()
        g = self._g
        cfg["url"] = g["url"].get().strip()
        cfg["poll_interval_sec"] = _num(g["poll_interval_sec"].get(), 30, is_int=True) or 30
        cfg["request_timeout_sec"] = _num(g["request_timeout_sec"].get(), 10, is_int=True) or 10
        cfg["teams_webhook_url"] = g["teams_webhook_url"].get().strip()
        cfg["cooldown_minutes"] = _num(g["cooldown_minutes"].get(), 15, is_int=True) or 15
        cfg["stale_minutes"] = _num(g["stale_minutes"].get(), 10, is_int=True) or 10
        cfg["quiet_hours"] = {
            "enabled": bool(g["quiet_enabled"].get()),
            "start": g["quiet_start"].get().strip() or "22:00",
            "end": g["quiet_end"].get().strip() or "07:00",
        }
        cfg["run_at_startup"] = bool(g["run_at_startup"].get())

        # 状態の呼び方（空欄は既定で補完）
        cfg["labels"] = {
            key: (g[f"label_{key}"].get().strip() or presets.DEFAULT_LABELS[key])
            for key in ("ok", "warn", "critical", "stale")
        }

        # sensors.json はユーザー専用のため設定画面からは触らない（cfg の既存値を保持）。

        rooms = dict(cfg.get("rooms", {}))
        for room, v in self._room_vars.items():
            rc = _deep_merge(DEFAULT_ROOM, rooms.get(room, {}))
            for key in ("temp", "humid"):
                lo, hi = v[key]
                rc[key] = {"min": _num(lo.get()), "max": _num(hi.get())}
            gate_mode, gate_val, inv_mode = v["lux_gate"]
            rc["lux_gate"] = {
                "mode": inv_mode.get(gate_mode.get(), "off"),
                "value": _num(gate_val.get(), 50) or 50,
            }
            rc["channels"] = {"toast": bool(v["toast"].get()), "teams": bool(v["teams"].get())}
            rc["stale_enabled"] = bool(v["stale_enabled"].get())
            rooms[room] = rc
        cfg["rooms"] = rooms

        wcfg = dict(cfg.get("widget", {}))
        wcfg["enabled"] = bool(self._w_enabled.get())
        wcfg["dock"] = self._w_dock_inv.get(self._w_dock_disp.get(), "taskbar")
        wcfg["items"] = [{"room": r, "metric": m} for r, m in self._w_items]
        cfg["widget"] = wcfg
        return cfg

    def _save(self) -> None:
        new_cfg = self._collect()
        startup.set_startup(new_cfg.get("run_at_startup", False))
        self.config.replace(new_cfg)
        log.info("設定を保存しました")
        try:
            self.on_saved()
        except Exception:
            log.exception("on_saved で例外")
        self._close()

    def _test_notify(self) -> None:
        self.notifier.test_notify(self._collect())

    def _close(self) -> None:
        if self.win is not None:
            self.win.destroy()
            self.win = None
