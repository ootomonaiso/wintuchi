"""EnvMonitor → overlay(Rust) 連携ブリッジ.

AppState の部屋状態から表示チップ（色解決済み）を作り、overlay が読む
``state.json``（= app_data_dir/overlay.state.json）へ原子的に書き出す。
overlay 実行ファイルの起動/停止も担う。

本体(poller/rules/notifier)には一切触れず、表示(overlay)だけを足す追加レイヤ。
失敗しても本体が止まらないよう、全て例外を飲み込む。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from .config import Config, _exe_dir, app_data_dir

log = logging.getLogger(__name__)

# しきい値配色（flyout のゲージ色に準拠）。色の決定は Python の責任。
GREEN, ORANGE, RED, GRAY, LUX = "#3BA55D", "#E8A33D", "#E24C4C", "#8A8A8A", "#4A90D9"

# metric -> (単位, Reading属性, 小数桁)
METRICS = {
    "temp": ("℃", "temp", 1),
    "humid": ("%", "humid", 0),
    "lux": ("lx", "lux", 0),
}


def state_path() -> Path:
    return app_data_dir() / "overlay.state.json"


def _color(metric: str, value: Optional[float], room_cfg: dict) -> str:
    if value is None:
        return GRAY
    if metric == "lux":
        return LUX  # 照度は閾値判定せず中立色
    b = room_cfg.get(metric, {}) or {}
    lo, hi = b.get("min"), b.get("max")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        return RED
    if lo is not None and hi is not None and hi > lo:
        span = hi - lo
        if (value - lo) <= 0.1 * span or (hi - value) <= 0.1 * span:
            return ORANGE
    return GREEN


def build_chips(state, config: Config) -> list[dict[str, Any]]:
    """表示チップ列を作る。widget.items（無ければ全部屋の気温）に従う。"""
    snap = config.snapshot()
    items = snap.get("widget", {}).get("items", [])
    rooms = {r.name: r for r in state.snapshot()}
    if not items:
        items = [{"room": n, "metric": "temp"} for n in sorted(rooms)]

    chips: list[dict[str, Any]] = []
    for it in items:
        room, metric = it.get("room"), it.get("metric")
        if metric not in METRICS:
            continue
        unit, attr, dec = METRICS[metric]
        rs = rooms.get(room)
        value = getattr(rs.latest, attr, None) if (rs and rs.latest) else None
        rc = config.room_config(room) if room else {}
        text = "--" if value is None else f"{value:.{dec}f}{unit}"
        chips.append({"label": room, "value": text, "fg": _color(metric, value, rc)})
    return chips


def write_state(state, config: Config, visible: bool = True) -> None:
    """overlay 用の state.json を原子的に書き出す（単一書き手）。

    ``visible`` が False なら overlay はウィンドウを隠す（プロセスは常駐のまま）。
    """
    try:
        data = {"visible": bool(visible), "chips": build_chips(state, config)}
        p = state_path()
        tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        log.exception("overlay state の書き出しに失敗")


class OverlayBridge:
    """overlay 実行ファイルの起動/停止を管理する。"""

    def __init__(self, config: Config):
        self.config = config
        self.proc: Optional[subprocess.Popen] = None

    def _enabled(self) -> bool:
        return bool(self.config.snapshot().get("overlay", {}).get("enabled", True))

    def _exe(self) -> Optional[Path]:
        """overlay exe を探す: config.overlay.exe → 環境変数 → EnvMonitor exe と同じ場所。"""
        ocfg = self.config.snapshot().get("overlay", {})
        candidates = [
            ocfg.get("exe"),
            os.environ.get("ENVMON_OVERLAY_EXE"),
            str(_exe_dir() / "envmon-overlay.exe"),
        ]
        for c in candidates:
            if c and Path(c).exists():
                return Path(c)
        return None

    def start(self) -> None:
        if not self._enabled():
            return
        exe = self._exe()
        if exe is None:
            log.warning("overlay 実行ファイルが見つからないため起動しません"
                        "（config.overlay.exe か環境変数 ENVMON_OVERLAY_EXE で指定可）")
            return
        try:
            self.proc = subprocess.Popen([str(exe)])
            log.info("overlay を起動: %s", exe)
        except Exception:
            log.exception("overlay の起動に失敗")

    def stop(self) -> None:
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None

    def apply_enabled(self) -> None:
        """設定の overlay.enabled に合わせて起動/停止を揃える（設定変更後に呼ぶ）。"""
        running = self.proc is not None and self.proc.poll() is None
        if self._enabled():
            if not running:
                self.start()
        elif running:
            self.stop()
