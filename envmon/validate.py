"""設定(config.json)の検証・正規化レイヤ.

Tk 設定画面（UI門番）を廃してヘッドレス化するため、不正な JSON が
唯一にして最大の故障点になる。全項目に型/範囲のフォールバックを持たせ、
補正があれば warnings に積む（ログ・HTML への表示用）。

適用点:
- ``config.load_config()`` 読み込み時（手編集 config.json を安全化）
- HTTP の ``POST /config`` 時（ブラウザから来た値を安全化）

方針:
- 既知スカラは型/範囲を強制。範囲外・型違いは既定へ落として warning。
- 未知キーは保持する（前方互換）。``_deep_merge(DEFAULT_CONFIG, data)``
  で既定を補完したうえで、既知項目だけ上書き検証する。
- ``sensors`` は書き換えない（sensors.json が権威。ここは読取キャッシュ）。
"""
from __future__ import annotations

import copy
from typing import Any

from . import presets
from .config import DEFAULT_CONFIG, DEFAULT_ROOM, _deep_merge
from .theme import is_hex_color

_TIME_FALLBACK = {"start": "22:00", "end": "07:00"}
_GATE_MODES = ("off", "above", "below")
_DOCK_MODES = ("taskbar", "float")
_WIDGET_METRICS = ("temp", "humid", "lux")


def _as_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off", ""):
            return False
    return default


def _as_number(v: Any, default: float | None) -> float | None:
    """数値へ。空/None は None（＝未設定）を許す場合に default=None を渡す。"""
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return default
    if lo is not None and n < lo:
        return lo
    if hi is not None and n > hi:
        return hi
    return n


def _as_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v)


def _as_time(v: Any, default: str) -> str:
    """"HH:MM" 形式へ正規化。不正は default。"""
    s = str(v or "").strip()
    parts = s.split(":")
    if len(parts) == 2:
        try:
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h < 24 and 0 <= m < 60:
                return f"{h:02d}:{m:02d}"
        except ValueError:
            pass
    return default


def _norm_room(name: str, rc_in: dict, warnings: list[str]) -> dict:
    rc = _deep_merge(DEFAULT_ROOM, rc_in if isinstance(rc_in, dict) else {})
    for key in ("temp", "humid"):
        band = rc.get(key) if isinstance(rc.get(key), dict) else {}
        lo = _as_number(band.get("min"), None)
        hi = _as_number(band.get("max"), None)
        if lo is not None and hi is not None and lo > hi:
            warnings.append(f"部屋「{name}」の{key}: 下限>上限のため入れ替えました")
            lo, hi = hi, lo
        rc[key] = {"min": lo, "max": hi}

    gate = rc.get("lux_gate") if isinstance(rc.get("lux_gate"), dict) else {}
    mode = gate.get("mode")
    if mode not in _GATE_MODES:
        if mode is not None:
            warnings.append(f"部屋「{name}」の照度ゲート mode が不正({mode})→off")
        mode = "off"
    rc["lux_gate"] = {"mode": mode, "value": _as_number(gate.get("value"), 50.0) or 50.0}

    ch = rc.get("channels") if isinstance(rc.get("channels"), dict) else {}
    rc["channels"] = {"toast": _as_bool(ch.get("toast"), True),
                      "teams": _as_bool(ch.get("teams"), True)}
    rc["stale_enabled"] = _as_bool(rc.get("stale_enabled"), True)
    return rc


def normalize(data: Any) -> tuple[dict, list[str]]:
    """config を正規化して (clean_data, warnings) を返す。

    data が dict でない/壊れている場合は既定を返す。
    """
    warnings: list[str] = []
    if not isinstance(data, dict):
        warnings.append("設定が読み取れなかったため既定値を使用しました")
        return copy.deepcopy(DEFAULT_CONFIG), warnings

    c = _deep_merge(DEFAULT_CONFIG, data)

    c["url"] = _as_str(c.get("url"), DEFAULT_CONFIG["url"]).strip()
    c["poll_interval_sec"] = _as_int(c.get("poll_interval_sec"), 30, lo=1)
    c["request_timeout_sec"] = _as_int(c.get("request_timeout_sec"), 10, lo=1)
    c["teams_webhook_url"] = _as_str(c.get("teams_webhook_url"), "").strip()
    c["cooldown_minutes"] = _as_int(c.get("cooldown_minutes"), 15, lo=0)
    c["stale_minutes"] = _as_int(c.get("stale_minutes"), 10, lo=1)
    c["run_at_startup"] = _as_bool(c.get("run_at_startup"), False)

    qh = c.get("quiet_hours") if isinstance(c.get("quiet_hours"), dict) else {}
    c["quiet_hours"] = {
        "enabled": _as_bool(qh.get("enabled"), False),
        "start": _as_time(qh.get("start"), _TIME_FALLBACK["start"]),
        "end": _as_time(qh.get("end"), _TIME_FALLBACK["end"]),
    }

    labels = c.get("labels") if isinstance(c.get("labels"), dict) else {}
    c["labels"] = {k: (_as_str(labels.get(k)).strip() or presets.DEFAULT_LABELS[k])
                   for k in ("ok", "warn", "critical", "stale")}

    colors_in = c.get("colors") if isinstance(c.get("colors"), dict) else {}
    colors_out = {}
    for k in ("ok", "warn", "critical", "stale", "lux"):
        v = colors_in.get(k)
        default = DEFAULT_CONFIG["colors"][k]
        if is_hex_color(v):
            colors_out[k] = v.strip()
        else:
            if v is not None:
                warnings.append(f"状態色「{k}」が不正な値({v})のため既定に戻しました")
            colors_out[k] = default
    c["colors"] = colors_out

    hy = c.get("hysteresis") if isinstance(c.get("hysteresis"), dict) else {}
    c["hysteresis"] = {
        "temp": _as_number(hy.get("temp"), 0.5) or 0.0,
        "humid": _as_number(hy.get("humid"), 2.0) or 0.0,
    }

    # sensors は書き換えない（sensors.json 権威）。dict であることだけ保証。
    if not isinstance(c.get("sensors"), dict):
        c["sensors"] = {}

    rooms_in = c.get("rooms") if isinstance(c.get("rooms"), dict) else {}
    c["rooms"] = {name: _norm_room(name, rc, warnings) for name, rc in rooms_in.items()}

    w = c.get("widget") if isinstance(c.get("widget"), dict) else {}
    dock = w.get("dock")
    if dock not in _DOCK_MODES:
        dock = "taskbar"
    items = []
    for it in (w.get("items") or []):
        if isinstance(it, dict) and it.get("metric") in _WIDGET_METRICS and it.get("room"):
            items.append({"room": str(it["room"]), "metric": it["metric"]})
    pos = w.get("pos")
    if not (isinstance(pos, (list, tuple)) and len(pos) == 2):
        pos = None
    c["widget"] = {
        "enabled": _as_bool(w.get("enabled"), False),
        "items": items,
        "dock": dock,
        "pos": list(pos) if pos else None,
        "taskbar_gap": _as_int(w.get("taskbar_gap"), 8, lo=0),
        "opacity": min(1.0, max(0.1, _as_number(w.get("opacity"), 0.96) or 0.96)),
    }

    o = c.get("overlay") if isinstance(c.get("overlay"), dict) else {}
    c["overlay"] = {
        "enabled": _as_bool(o.get("enabled"), True),
        "exe": _as_str(o.get("exe"), "").strip(),
    }

    return c, warnings
