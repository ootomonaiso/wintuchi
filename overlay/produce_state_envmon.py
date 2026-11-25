"""本線: EnvMonitor の実データ（温度/湿度）を overlay の state.json に流す。

責任分離:
  - Python(ここ) が EnvMonitor の config/poller で値を取り、しきい値から色を決める。
  - Rust overlay は state.json を読んで描くだけ。

依存は Tk 非依存の `envmon.config` / `envmon.poller` のみ（ヘッドレス）。
色は flyout のゲージ配色に準じた簡易版（緑=正常 / 橙=接近 / 赤=範囲外 / 灰=不明）。

実行（venv 推奨）:
    # 1) モックサーバ（例: 3部屋・mixed）
    set ENVMON_SCENARIO=mixed
    python tools/mock_server.py 8099
    # 2) このプロデューサ（接続先を上書き）
    set ENVMON_URL=http://127.0.0.1:8099/env1.php
    python overlay/produce_state_envmon.py

接続先は ENVMON_URL（無ければ EnvMonitor の config.json の url）。
表示項目は config.json の widget.items（無ければ全部屋の気温）。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from envmon.config import load_config  # noqa: E402
from envmon.poller import latest_per_sensor, parse_records  # noqa: E402

STATE_PATH = r"C:/Users/ootom/envmon-overlay.state.json"
INTERVAL_SEC = 2.0

GREEN, ORANGE, RED, GRAY, LUX = "#3BA55D", "#E8A33D", "#E24C4C", "#8A8A8A", "#4A90D9"

# metric -> (単位, Reading属性, 小数桁)
METRICS = {
    "temp": ("℃", "temp", 1),
    "humid": ("%", "humid", 0),
    "lux": ("lx", "lux", 0),
}


def color_for(metric: str, value, room_cfg: dict) -> str:
    """しきい値から色を決める（色の決定は Python の責任）。"""
    if value is None:
        return GRAY
    if metric == "lux":
        return LUX  # 照度は閾値判定せず中立色
    b = room_cfg.get(metric, {}) or {}
    lo, hi = b.get("min"), b.get("max")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        return RED
    # レンジ端に近ければ橙
    if lo is not None and hi is not None and hi > lo:
        span = hi - lo
        near = (value - lo) <= 0.1 * span or (hi - value) <= 0.1 * span
        if near:
            return ORANGE
    return GREEN


def build_chips(cfg) -> list[dict]:
    snap = cfg.snapshot()
    url = os.environ.get("ENVMON_URL") or snap.get("url", "")
    if not url:
        return []
    try:
        resp = requests.get(url, timeout=snap.get("request_timeout_sec", 10))
        resp.raise_for_status()
        latest = latest_per_sensor(parse_records(resp.text))
    except Exception as e:  # 取得失敗時は空（overlay は内蔵表示へフォールバック）
        print("fetch failed:", e)
        return []

    # センサ -> 部屋、部屋 -> 最新 Reading
    room_latest: dict[str, object] = {}
    for sid, r in latest.items():
        room = cfg.room_for_sensor(sid)
        cur = room_latest.get(room)
        if cur is None or r.timestamp >= cur.timestamp:
            room_latest[room] = r

    # 表示項目: widget.items（無ければ全部屋の気温）
    items = snap.get("widget", {}).get("items", [])
    if not items:
        items = [{"room": rm, "metric": "temp"} for rm in sorted(room_latest)]

    chips = []
    for it in items:
        room, metric = it.get("room"), it.get("metric")
        if metric not in METRICS:
            continue
        unit, attr, dec = METRICS[metric]
        r = room_latest.get(room)
        value = getattr(r, attr, None) if r is not None else None
        rc = cfg.room_config(room) if room else {}
        text = "--" if value is None else f"{value:.{dec}f}{unit}"
        chips.append({
            "label": room,
            "value": text,
            "fg": color_for(metric, value, rc),
        })
    return chips


def write_atomic(path: str, data: dict) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def main() -> None:
    cfg = load_config()
    print(f"writing {STATE_PATH} every {INTERVAL_SEC}s (Ctrl+C で停止)")
    try:
        while True:
            chips = build_chips(cfg)
            if chips:
                write_atomic(STATE_PATH, {"chips": chips})
            time.sleep(INTERVAL_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(STATE_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    main()
