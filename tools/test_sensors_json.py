"""sensors.json の生成・外部編集反映・堅牢性テスト（隔離APPDATAで実行）。"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 隔離した APPDATA を使用
tmp = Path(__file__).resolve().parent.parent / "_sensors_test_appdata"
shutil.rmtree(tmp, ignore_errors=True)
os.environ["APPDATA"] = str(tmp)

from envmon.config import load_config, sensors_path  # noqa: E402

ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("  OK  " if cond else " FAIL ") + name)


cfg = load_config()
cfg.set_sensors({"1": "会議室A", "2": "サーバ室"})
check("sensors.json が生成される", sensors_path().exists())
content = sensors_path().read_text(encoding="utf-8")
check("日本語が保持される", "会議室A" in content)

# 外部編集 -> reload
time.sleep(0.05)
sensors_path().write_text(
    json.dumps({"1": "会議室A", "2": "サーバ室", "5": "実験室"}, ensure_ascii=False),
    encoding="utf-8")
check("外部編集を reload で検知", cfg.reload_sensors() is True)
check("追加センサが反映(5->実験室)", cfg.room_for_sensor(5) == "実験室")

# 変更なしは False
check("変更なしの reload は False", cfg.reload_sensors() is False)

# 壊れたJSONでも落ちず、既存値を維持
sensors_path().write_text("{ broken json", encoding="utf-8")
check("壊れたJSONでも例外なし(False)", cfg.reload_sensors() is False)
check("壊れた後も既存値を維持", cfg.room_for_sensor(5) == "実験室")

# BOM付きでも読める
sensors_path().write_bytes(
    b"\xef\xbb\xbf" + json.dumps({"7": "屋上"}, ensure_ascii=False).encode("utf-8"))
check("BOM付きJSONも読める", cfg.reload_sensors() and cfg.room_for_sensor(7) == "屋上")

shutil.rmtree(tmp, ignore_errors=True)
print("\n結果:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
