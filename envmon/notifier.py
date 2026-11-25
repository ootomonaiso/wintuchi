"""通知ディスパッチ: クールダウン・静音時間を集中管理し各チャネルへ配信."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, time as dtime
from typing import Optional

from . import teams, toast
from .rules import AlertEvent

log = logging.getLogger(__name__)


def _parse_hhmm(s: str) -> Optional[dtime]:
    try:
        h, m = s.split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(cfg: dict, now: Optional[datetime] = None) -> bool:
    qh = cfg.get("quiet_hours", {})
    if not qh.get("enabled"):
        return False
    start = _parse_hhmm(qh.get("start", "22:00"))
    end = _parse_hhmm(qh.get("end", "07:00"))
    if not start or not end:
        return False
    now_t = (now or datetime.now()).time()
    if start <= end:
        return start <= now_t < end
    # 日跨ぎ（例 22:00-07:00）
    return now_t >= start or now_t < end


class Notifier:
    """アラートイベントを各チャネルへ配信する."""

    def __init__(self):
        self._lock = threading.Lock()
        # (room, metric) -> 最終通知時刻
        self._last_notified: dict[tuple[str, str], datetime] = {}

    def _cooldown_ok(self, key: tuple[str, str], cooldown_min: int, now: datetime) -> bool:
        last = self._last_notified.get(key)
        if last is None:
            return True
        return (now - last).total_seconds() >= cooldown_min * 60

    def dispatch(self, ev: AlertEvent, room_cfg: dict, global_cfg: dict,
                 now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        channels = room_cfg.get("channels", {})
        key = (ev.room, ev.metric)

        if ev.kind == "alert":
            # クールダウン判定（アラートのみ。復旧は常に1回通知）
            cooldown = int(global_cfg.get("cooldown_minutes", 15))
            with self._lock:
                if not self._cooldown_ok(key, cooldown, now):
                    return
                self._last_notified[key] = now
        else:  # recovery
            # クールダウン状態をリセットして、次回の異常を即通知できるように
            with self._lock:
                self._last_notified.pop(key, None)

        # 静音時間中は「異常」通知のみ抑制する。復旧(recovery)は「常に1回」通知する
        # 設計なので、静音時間でも握りつぶさず知らせる（夜間に復旧が消えて
        # 翌朝まで誤解する事故を防ぐ）。画面上のバッジは別途反映される。
        if ev.kind == "alert" and in_quiet_hours(global_cfg, now):
            log.info("静音時間のため通知抑制: %s", ev.message)
            return

        title = "環境モニタ"
        if channels.get("toast", True):
            toast.show_toast(title, ev.message)

        if channels.get("teams", True) and global_cfg.get("teams_webhook_url"):
            self._send_teams_async(ev, global_cfg)

    def _send_teams_async(self, ev: AlertEvent, global_cfg: dict) -> None:
        url = global_cfg.get("teams_webhook_url", "")
        timeout = int(global_cfg.get("request_timeout_sec", 10))
        labels = global_cfg.get("labels") or {}
        payload = teams.build_payload(
            room=ev.room,
            metric=ev.metric,
            message=ev.message,
            severity=ev.severity,
            value=ev.value,
            timestamp=datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            status_label=labels.get(ev.severity.key),
        )
        threading.Thread(
            target=teams.send, args=(url, payload, timeout),
            name="teams-send", daemon=True,
        ).start()

    def test_notify(self, global_cfg: dict) -> None:
        """設定画面の「テスト通知」用。クールダウン/静音を無視して即送信。"""
        msg = "テスト通知: 環境モニタは正常に動作しています。"
        toast.show_toast("環境モニタ（テスト）", msg)
        url = global_cfg.get("teams_webhook_url", "")
        if url:
            from .model import Severity
            payload = teams.build_payload(
                room="テスト", metric="test", message=msg,
                severity=Severity.OK, value=None,
                timestamp=datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            )
            teams.send(url, payload, int(global_cfg.get("request_timeout_sec", 10)))
