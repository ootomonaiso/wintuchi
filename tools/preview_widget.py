"""デスクトップウィジェットのプレビュー（スクショ用）。"""
import copy
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import customtkinter as ctk  # noqa: E402
from envmon.config import Config, DEFAULT_CONFIG  # noqa: E402
from envmon.model import AppState, Reading, RoomState, Severity  # noqa: E402
from envmon.widget import DesktopWidget  # noqa: E402

_data = copy.deepcopy(DEFAULT_CONFIG)
_data["rooms"] = {
    "会議室A": {"temp": {"min": 18, "max": 30}, "voltage": {"min": 2.6, "max": None}},
    "サーバ室": {"temp": {"min": 10, "max": 28}, "voltage": {"min": 2.6, "max": None}},
}
_data["widget"] = {
    "enabled": True, "pos": None, "opacity": 0.97,
    "items": [
        {"room": "会議室A", "metric": "temp"},
        {"room": "会議室A", "metric": "humid"},
        {"room": "サーバ室", "metric": "voltage"},
        {"room": "サーバ室", "metric": "temp"},
    ],
}
config = Config(_data)

state = AppState()


def mkroom(name, sid, temp, humid, lux, volt, sev, alerts):
    rs = RoomState(name=name, sensor_ids=[sid])
    rs.latest = Reading(sensor_id=sid, timestamp=datetime.now(), temp=temp, humid=humid, lux=lux, voltage=volt)
    rs.severity = sev
    rs.active_alerts = set(alerts)
    state.rooms[name] = rs


mkroom("会議室A", 1, 35.2, 45.0, 800.0, 3.1, Severity.WARN, {"temp"})
mkroom("サーバ室", 2, 23.0, 52.0, 5.0, 2.4, Severity.CRITICAL, {"voltage"})

ctk.set_appearance_mode("dark")
root = ctk.CTk()
root.withdraw()
wdg = DesktopWidget(root, state, config, on_settings=lambda: print("settings"))
wdg.show()
root.after(6000, root.destroy)
root.mainloop()
