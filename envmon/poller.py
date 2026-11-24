"""/env1.php の定期取得・パース・状態更新・判定ディスパッチ."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Callable, Optional

import requests

from .config import Config
from .model import AppState, Reading, RoomState
from .rules import evaluate_room

log = logging.getLogger(__name__)

_TS_FORMATS = (
    "%Y/%m/%d %H:%M:%S.%f",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
)


def _parse_ts(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _to_float(x) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_records(text: str) -> list[Reading]:
    """レスポンス本文（JSON配列の配列）を Reading 列にパース.

    形式: [[null, "YYYY/MM/DD HH:MM:SS.sssss", sensor_id, temp, humid, lux, voltage], ...]
    不正・欠損レコードはスキップしてログに残す。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("JSONパース失敗: %s", e)
        return []

    # 単一レコード（[null, ts, id, ...]）が返るケースも配列の配列に正規化
    if data and isinstance(data, list) and data and not isinstance(data[0], list):
        data = [data]

    readings: list[Reading] = []
    for row in data:
        if not isinstance(row, list) or len(row) < 3:
            continue
        try:
            sensor_id = int(row[2])
        except (TypeError, ValueError):
            log.debug("センサID不正のためスキップ: %r", row)
            continue
        ts = _parse_ts(str(row[1])) or datetime.now()
        r = Reading(
            sensor_id=sensor_id,
            timestamp=ts,
            temp=_to_float(row[3]) if len(row) > 3 else None,
            humid=_to_float(row[4]) if len(row) > 4 else None,
            lux=_to_float(row[5]) if len(row) > 5 else None,
            voltage=_to_float(row[6]) if len(row) > 6 else None,
        )
        readings.append(r)
    return readings


def latest_per_sensor(readings: list[Reading]) -> dict[int, Reading]:
    """センサIDごとにタイムスタンプ最大の1件を残す。"""
    out: dict[int, Reading] = {}
    for r in readings:
        cur = out.get(r.sensor_id)
        if cur is None or r.timestamp >= cur.timestamp:
            out[r.sensor_id] = r
    return out


class Poller:
    """バックグラウンドで定期取得して状態更新・通知するワーカ."""

    def __init__(self, config: Config, state: AppState, notifier,
                 on_update: Optional[Callable[[], None]] = None):
        self.config = config
        self.state = state
        self.notifier = notifier
        self.on_update = on_update
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._session = requests.Session()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def poll_now(self) -> None:
        """設定変更時などに即時ポーリングを促す。"""
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as e:  # ワーカを止めない
                log.exception("ポーリング中に例外: %s", e)
            interval = max(5, int(self.config.get("poll_interval_sec", 30)))
            self._wake.wait(timeout=interval)
            self._wake.clear()

    def _poll_once(self) -> None:
        # 外部で sensors.json が編集されていれば取り込む
        self.config.reload_sensors()
        cfg = self.config.snapshot()
        url = cfg.get("url", "")
        timeout = cfg.get("request_timeout_sec", 10)
        readings: list[Reading] = []
        if url:
            try:
                resp = self._session.get(url, timeout=timeout)
                resp.raise_for_status()
                readings = parse_records(resp.text)
                with self.state.lock:
                    self.state.last_poll_ok = datetime.now()
                    self.state.last_poll_error = None
            except requests.RequestException as e:
                with self.state.lock:
                    self.state.last_poll_error = str(e)
                log.warning("取得失敗(%s): %s", url, e)
                # 取得失敗でも既存状態で停止検知の評価は行う

        self._update_state(readings, cfg)
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                log.exception("on_update コールバックで例外")

    def _update_state(self, readings: list[Reading], cfg: dict) -> None:
        now = datetime.now()
        latest = latest_per_sensor(readings)

        # センサ -> 部屋 の割り当て。対応表(sensors.json)はユーザー専用のためアプリは
        # 書き換えない。未割当センサは「センサ<ID>」の仮名で表示するだけ（永続化しない）。
        sensors_cfg = dict(cfg.get("sensors", {}))
        room_to_sensors: dict[str, list[int]] = {}
        sensor_room: dict[int, str] = {}
        for sid in latest:
            name = sensors_cfg.get(str(sid)) or f"センサ{sid}"
            sensor_room[sid] = name
            room_to_sensors.setdefault(name, []).append(sid)

        with self.state.lock:
            # 既知の部屋すべて（設定済み + 今回受信分）を評価対象にする。
            # 今回受信の無い部屋も、過去に状態があれば停止検知のため評価する。
            configured_rooms = set(sensors_cfg.values())
            known_rooms = set(room_to_sensors) | set(self.state.rooms) | configured_rooms

            all_events = []
            for rname in known_rooms:
                rs = self.state.get_room(rname)
                sids = room_to_sensors.get(rname, rs.sensor_ids)
                rs.sensor_ids = sorted(set(sids)) if sids else rs.sensor_ids
                # この部屋の最新 Reading（受信があれば更新）
                room_readings = [latest[s] for s in room_to_sensors.get(rname, []) if s in latest]
                if room_readings:
                    rs.latest = max(room_readings, key=lambda r: r.timestamp)

                room_cfg = self.config.room_config(rname)
                events = evaluate_room(rs, room_cfg, cfg, now=now)
                for ev in events:
                    ev_room_cfg = room_cfg
                    all_events.append((ev, ev_room_cfg))

        # 通知はロック外で（ネットワークI/Oを伴うため）
        for ev, room_cfg in all_events:
            self.notifier.dispatch(ev, room_cfg, cfg)
