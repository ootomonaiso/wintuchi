"""設定画面プレビュー（スクショ用）。引数でタブ指定: 全般/部屋/ウィジェット。"""
import copy
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import customtkinter as ctk  # noqa: E402
from envmon.config import Config, DEFAULT_CONFIG  # noqa: E402
from envmon.model import AppState, Reading, RoomState, Severity  # noqa: E402
from envmon.settings_ui import SettingsWindow  # noqa: E402

tab = sys.argv[1] if len(sys.argv) > 1 else "全般"

_data = copy.deepcopy(DEFAULT_CONFIG)
_data["url"] = "http://192.168.1.10/env1.php"
_data["sensors"] = {"1": "会議室A", "2": "サーバ室", "3": "応接室"}
_data["rooms"] = {
    "会議室A": {"temp": {"min": 18, "max": 30}, "voltage": {"min": 2.6, "max": None}},
    "サーバ室": {"temp": {"min": 10, "max": 28}, "voltage": {"min": 2.6, "max": None}},
    "応接室": {"temp": {"min": 10, "max": 30}},
}
_data["widget"] = {"enabled": True, "dock": "taskbar", "pos": None, "opacity": 0.96,
                   "items": [{"room": "会議室A", "metric": "temp"},
                             {"room": "サーバ室", "metric": "voltage"}]}
config = Config(_data)

state = AppState()
for n, sid in (("会議室A", 1), ("サーバ室", 2), ("応接室", 3)):
    rs = RoomState(name=n, sensor_ids=[sid])
    rs.latest = Reading(sensor_id=sid, timestamp=datetime.now(), temp=24, humid=50, lux=100, voltage=3.0)
    state.rooms[n] = rs


class _Noti:
    def test_notify(self, cfg):
        print("test_notify")


ctk.set_appearance_mode("dark")
root = ctk.CTk()
root.withdraw()
sw = SettingsWindow(root, config, state, _Noti(), on_saved=lambda: None)
sw.open()
sw.win.geometry("600x670+120+80")
sw.win.attributes("-topmost", True)
sw.win.lift()
sw.win.after(200, lambda: (sw.win.lift(), sw.win.attributes("-topmost", True)))
try:
    sw.tabs.set(tab)
except Exception as e:
    print("tab set error", e)
root.after(6000, root.destroy)
root.mainloop()
