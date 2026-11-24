"""ヘッドレスなコアロジック検証（GUI不要）。トーストはモック化する。"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from envmon import toast  # noqa: E402
from envmon.poller import parse_records, latest_per_sensor  # noqa: E402
from envmon.model import RoomState, Severity  # noqa: E402
from envmon.rules import evaluate_room  # noqa: E402
from envmon.notifier import Notifier, in_quiet_hours  # noqa: E402
from envmon.config import DEFAULT_ROOM, _deep_merge  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name}")


print("== パース ==")
sample = '[[null,"2022/02/17 12:55:55.21793",1,35.2,45.0,800.0,3.1],[null,"2022/02/17 12:56:00.10000",1,34.0,46.0,790.0,3.1],[null,"2022/02/17 12:55:50.00000",2,22.0,50.0,10.0,2.4]]'
rs = parse_records(sample)
check("3レコードをパース", len(rs) == 3)
latest = latest_per_sensor(rs)
check("センサ1は最新(12:56:00)を採用", abs(latest[1].temp - 34.0) < 1e-6)
check("センサ2の電圧=2.4", abs(latest[2].voltage - 2.4) < 1e-6)

# 壊れたデータ・単一レコード
check("空配列は空", parse_records("[]") == [])
check("不正JSONは空", parse_records("not json") == [])
single = parse_records('[null,"2022/02/17 12:00:00.00000",5,20.0,40.0,100.0,3.0]')
check("単一レコードも配列化", len(single) == 1 and single[0].sensor_id == 5)

print("== 閾値 + ヒステリシス ==")
room_cfg = _deep_merge(DEFAULT_ROOM, {"temp": {"min": 10, "max": 30}, "lux_gate": {"mode": "off"}})
g = {"stale_minutes": 10, "hysteresis": {"temp": 0.5}}
room = RoomState(name="A")
room.latest = latest[1]  # 34.0℃ > 30
evs = evaluate_room(room, room_cfg, g)
check("高温でalert発報", any(e.metric == "temp" and e.kind == "alert" for e in evs))
check("severity=WARN", room.severity == Severity.WARN)

# 29.8℃: 上限30-0.5=29.5 をまだ上回るのでlatch継続
from envmon.model import Reading  # noqa: E402
room.latest = Reading(sensor_id=1, timestamp=datetime.now(), temp=29.8, humid=45, lux=800, voltage=3.1)
evs = evaluate_room(room, room_cfg, g)
check("ヒステリシス域内はlatch継続", room.alert_latched.get("temp") is True)
# 29.0℃: 29.5を下回るので解除+recovery
room.latest = Reading(sensor_id=1, timestamp=datetime.now(), temp=29.0, humid=45, lux=800, voltage=3.1)
evs = evaluate_room(room, room_cfg, g)
check("閾値復帰でrecovery", any(e.kind == "recovery" for e in evs))
check("latch解除", room.alert_latched.get("temp") is False)

print("== 照度ゲート ==")
# above: lux>=50 のときのみ通知
gate_cfg = _deep_merge(DEFAULT_ROOM, {"temp": {"min": 10, "max": 30},
                                      "lux_gate": {"mode": "above", "value": 50}})
room2 = RoomState(name="B")
room2.latest = Reading(sensor_id=9, timestamp=datetime.now(), temp=35, humid=45, lux=10, voltage=3.1)
evs = evaluate_room(room2, gate_cfg, g)
check("暗い(10lux)時はalert抑制", not any(e.kind == "alert" for e in evs))
check("ただし内部latchは立つ", room2.alert_latched.get("temp") is True)
room2b = RoomState(name="B2")
room2b.latest = Reading(sensor_id=9, timestamp=datetime.now(), temp=35, humid=45, lux=100, voltage=3.1)
evs = evaluate_room(room2b, gate_cfg, g)
check("明るい(100lux)時はalert発報", any(e.kind == "alert" for e in evs))

print("== センサ停止検知 ==")
room3 = RoomState(name="C")
old = Reading(sensor_id=3, timestamp=datetime.now(), temp=22, humid=50, lux=100, voltage=3.0)
old.received_at = datetime.now() - timedelta(minutes=20)
room3.latest = old
evs = evaluate_room(room3, DEFAULT_ROOM, {"stale_minutes": 10, "hysteresis": {}})
check("20分前受信でstale発報", any(e.metric == "stale" and e.kind == "alert" for e in evs))
check("severity=STALE", room3.severity == Severity.STALE)

print("== クールダウン ==")
# toast をモック化
sent = []
toast.show_toast = lambda t, b: (sent.append((t, b)) or True)
n = Notifier()
from envmon.rules import AlertEvent  # noqa: E402
ev = AlertEvent("A", "temp", "alert", Severity.WARN, "A 気温: 35℃")
gcfg = {"cooldown_minutes": 15, "quiet_hours": {"enabled": False}, "teams_webhook_url": ""}
rcfg = {"channels": {"toast": True, "teams": False}}
now = datetime.now()
n.dispatch(ev, rcfg, gcfg, now=now)
n.dispatch(ev, rcfg, gcfg, now=now + timedelta(minutes=1))   # クールダウン内 -> 抑制
n.dispatch(ev, rcfg, gcfg, now=now + timedelta(minutes=16))  # 経過 -> 再送
check("クールダウンで連投抑制(送信2回)", len(sent) == 2)

print("== 静音時間 ==")
qcfg = {"quiet_hours": {"enabled": True, "start": "22:00", "end": "07:00"}}
check("23:00は静音", in_quiet_hours(qcfg, datetime(2026, 1, 1, 23, 0)))
check("03:00は静音(日跨ぎ)", in_quiet_hours(qcfg, datetime(2026, 1, 1, 3, 0)))
check("12:00は非静音", not in_quiet_hours(qcfg, datetime(2026, 1, 1, 12, 0)))

print(f"\n結果: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
