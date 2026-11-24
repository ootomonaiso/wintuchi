"""判定ロジック: 閾値・照度ゲート・ヒステリシス・センサ停止検知.

evaluate_room() が RoomState を評価し、通知すべきアラートイベント列を返す。
RoomState.alert_latched / severity / active_alerts を副作用として更新する。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .model import Reading, RoomState, Severity

# 監視（しきい値判定）する metric キー -> (表示名, 単位, Reading属性名)
# ※電圧は監視対象外。照度は閾値判定せず通知ゲート専用（下の lux_gate）。
METRICS = {
    "temp": ("気温", "℃", "temp"),
    "humid": ("湿度", "%", "humid"),
}


@dataclass
class AlertEvent:
    room: str
    metric: str          # "temp" | "humid" | "voltage" | "stale"
    kind: str            # "alert" | "recovery"
    severity: Severity
    message: str
    value: Optional[float] = None


def _metric_severity(metric: str, direction: str) -> Severity:
    # 低電圧は重大、それ以外の閾値超過は警告
    if metric == "voltage" and direction == "low":
        return Severity.CRITICAL
    return Severity.WARN


def _lux_gate_allows(lux: Optional[float], gate: dict[str, Any]) -> bool:
    """照度ゲート: 通知を許可するか。lux 不明時は許可（ゲートしない）。"""
    mode = gate.get("mode", "off")
    if mode == "off" or lux is None:
        return True
    value = gate.get("value", 0.0)
    if mode == "above":
        return lux >= value
    if mode == "below":
        return lux <= value
    return True


def _eval_threshold(latched: bool, v: float, lo: Optional[float],
                    hi: Optional[float], h: float) -> tuple[bool, str]:
    """ヒステリシス付き閾値判定。

    戻り値 (new_latched, direction)。direction は "high"/"low"/""。
    発報中は閾値から h だけ戻るまで解除しない。
    """
    if latched:
        high_clear = (hi is None) or (v <= hi - h)
        low_clear = (lo is None) or (v >= lo + h)
        if high_clear and low_clear:
            return False, ""
        # まだ発報継続。方向を再判定（表示用）。
        if hi is not None and v > hi - h:
            return True, "high"
        return True, "low"
    else:
        if hi is not None and v > hi:
            return True, "high"
        if lo is not None and v < lo:
            return True, "low"
        return False, ""


def evaluate_room(room: RoomState, room_cfg: dict[str, Any],
                  global_cfg: dict[str, Any], now: Optional[datetime] = None) -> list[AlertEvent]:
    """部屋を評価してアラートイベント列を返す（RoomState を更新）。"""
    now = now or datetime.now()
    events: list[AlertEvent] = []
    hysteresis = global_cfg.get("hysteresis", {})
    active: set[str] = set()
    worst = Severity.OK

    # --- センサ停止検知 ---
    stale_minutes = global_cfg.get("stale_minutes", 10)
    stale_enabled = room_cfg.get("stale_enabled", True)
    is_stale = False
    age_min = 0.0
    last_seen = room.last_seen
    if stale_enabled and last_seen is not None:
        age_min = (now - last_seen).total_seconds() / 60.0
        is_stale = age_min > stale_minutes
    was_stale = room.alert_latched.get("stale", False)
    if is_stale:
        room.alert_latched["stale"] = True
        active.add("stale")
        worst = max(worst, Severity.STALE)
        mins = int(age_min)
        events.append(AlertEvent(room.name, "stale", "alert", Severity.STALE,
                                 f"{room.name}: センサ応答なし（{mins}分間更新なし）"))
    elif was_stale:
        room.alert_latched["stale"] = False
        events.append(AlertEvent(room.name, "stale", "recovery", Severity.OK,
                                 f"{room.name}: センサが復旧しました"))

    # --- 閾値判定（最新値が無ければスキップ）---
    reading: Optional[Reading] = room.latest
    if reading is not None and not is_stale:
        lux_gate = room_cfg.get("lux_gate", {"mode": "off"})
        gate_ok = _lux_gate_allows(reading.lux, lux_gate)
        for metric, (disp, unit, attr) in METRICS.items():
            v = getattr(reading, attr)
            if v is None:
                continue
            bounds = room_cfg.get(metric, {})
            lo = bounds.get("min")
            hi = bounds.get("max")
            if lo is None and hi is None:
                continue
            h = hysteresis.get(metric, 0.0)
            prev = room.alert_latched.get(metric, False)
            latched, direction = _eval_threshold(prev, v, lo, hi, h)
            room.alert_latched[metric] = latched
            if latched:
                sev = _metric_severity(metric, direction)
                worst = max(worst, sev)
                active.add(metric)
                # 照度ゲートで抑制される場合は通知イベントを出さない（状態は保持）
                if gate_ok:
                    limit = hi if direction == "high" else lo
                    arrow = "超過" if direction == "high" else "下回り"
                    events.append(AlertEvent(
                        room.name, metric, "alert", sev,
                        f"{room.name} {disp}: {v:g}{unit}（{arrow} / 閾値{limit:g}{unit}）",
                        value=v))
            elif prev:
                events.append(AlertEvent(
                    room.name, metric, "recovery", Severity.OK,
                    f"{room.name} {disp}: {v:g}{unit} 正常に戻りました", value=v))

    room.active_alerts = active
    room.severity = worst
    return events
