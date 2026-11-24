"""データモデル: 測定レコード・部屋状態・アプリ全体状態."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional


class Severity(IntEnum):
    """状態の深刻度。値が大きいほど深刻（トレイ色の決定に使用）。"""

    OK = 0
    WARN = 1       # 閾値超過（警告）
    CRITICAL = 2   # 低電圧など重大
    STALE = 3      # センサ停止/通信ダウン

    @property
    def color(self) -> str:
        return {
            Severity.OK: "#3BA55D",       # 緑
            Severity.WARN: "#E8A33D",     # 橙
            Severity.CRITICAL: "#D83C3C",  # 赤
            Severity.STALE: "#8A8A8A",    # 灰
        }[self]

    @property
    def key(self) -> str:
        """設定ファイル（labels）で使う安定キー。"""
        return {
            Severity.OK: "ok",
            Severity.WARN: "warn",
            Severity.CRITICAL: "critical",
            Severity.STALE: "stale",
        }[self]

    @property
    def label(self) -> str:
        # 「異常」のような強い言葉は避けた既定（設定の labels で上書き可能）。
        return {
            Severity.OK: "正常",
            Severity.WARN: "注意",
            Severity.CRITICAL: "要確認",
            Severity.STALE: "応答なし",
        }[self]


@dataclass
class Reading:
    """センサ1台の1レコード."""

    sensor_id: int
    timestamp: datetime
    temp: Optional[float] = None
    humid: Optional[float] = None
    lux: Optional[float] = None
    voltage: Optional[float] = None
    received_at: datetime = field(default_factory=datetime.now)


@dataclass
class RoomState:
    """部屋（1つ以上のセンサ）の現在状態."""

    name: str
    sensor_ids: list[int] = field(default_factory=list)
    latest: Optional[Reading] = None
    severity: Severity = Severity.OK
    # 現在アクティブなアラート種別（metric名 or "stale"）の集合
    active_alerts: set[str] = field(default_factory=set)
    # metric -> 発報中かどうか（ヒステリシス用）
    alert_latched: dict[str, bool] = field(default_factory=dict)

    @property
    def last_seen(self) -> Optional[datetime]:
        return self.latest.received_at if self.latest else None


class AppState:
    """全部屋の状態を保持するスレッドセーフなストア.

    poller スレッドが更新し、UI スレッドが読む。
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.rooms: dict[str, RoomState] = {}
        self.last_poll_ok: Optional[datetime] = None
        self.last_poll_error: Optional[str] = None

    def get_room(self, name: str) -> RoomState:
        with self.lock:
            rs = self.rooms.get(name)
            if rs is None:
                rs = RoomState(name=name)
                self.rooms[name] = rs
            return rs

    def worst_severity(self) -> Severity:
        with self.lock:
            if not self.rooms:
                return Severity.OK
            return max((r.severity for r in self.rooms.values()), default=Severity.OK)

    def snapshot(self) -> list[RoomState]:
        """UI 表示用に部屋状態のスナップショットを返す（名前順）。"""
        with self.lock:
            import copy
            return [copy.deepcopy(r) for r in sorted(self.rooms.values(), key=lambda x: x.name)]
