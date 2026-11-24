"""フライアウトUIのプレビュー（スクショ用）。実データ風の状態を注入して表示する。"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import customtkinter as ctk  # noqa: E402
from envmon.config import Config, DEFAULT_CONFIG  # noqa: E402
from envmon.model import AppState, Reading, RoomState, Severity  # noqa: E402
from envmon.flyout import Flyout  # noqa: E402

import copy  # noqa: E402
_data = copy.deepcopy(DEFAULT_CONFIG)
_data["rooms"] = {
    "会議室A": {"temp": {"min": 18, "max": 30}, "humid": {"min": 30, "max": 70}, "voltage": {"min": 2.6, "max": None}},
    "サーバ室": {"temp": {"min": 10, "max": 28}, "humid": {"min": 20, "max": 80}, "voltage": {"min": 2.6, "max": None}},
    "応接室": {"temp": {"min": 10, "max": 30}, "humid": {"min": 20, "max": 80}, "voltage": {"min": 2.6, "max": None}},
    "倉庫": {"temp": {"min": 5, "max": 35}, "humid": {"min": 10, "max": 90}, "voltage": {"min": 2.6, "max": None}},
}
config = Config(_data)

state = AppState()


def mkroom(name, sid, temp, humid, lux, volt, sev, alerts, age_min=0):
    rs = RoomState(name=name, sensor_ids=[sid])
    r = Reading(sensor_id=sid, timestamp=datetime.now(), temp=temp, humid=humid, lux=lux, voltage=volt)
    r.received_at = datetime.now() - timedelta(minutes=age_min)
    rs.latest = r
    rs.severity = sev
    rs.active_alerts = set(alerts)
    state.rooms[name] = rs


mkroom("会議室A", 1, 35.2, 45.0, 800.0, 3.1, Severity.WARN, {"temp"})
mkroom("サーバ室", 2, 23.0, 52.0, 5.0, 2.4, Severity.CRITICAL, {"voltage"})
mkroom("応接室", 3, 21.5, 60.0, 300.0, 3.2, Severity.OK, set())
mkroom("倉庫", 4, 18.0, 70.0, 0.0, 3.0, Severity.STALE, {"stale"}, age_min=25)
state.last_poll_ok = datetime.now()

ctk.set_appearance_mode("dark")
root = ctk.CTk()
root.withdraw()
fly = Flyout(root, state, config, on_room_click=lambda n: print("click", n), on_settings=lambda: print("settings"))
fly.show()

# 一定時間表示してから終了（外部スクショ用）
root.after(6000, root.destroy)
root.mainloop()
