"""実際にモックサーバを叩いて poller->rules->notifier を通す統合テスト."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from envmon import toast  # noqa: E402
from envmon.config import load_config  # noqa: E402
from envmon.model import AppState, Severity  # noqa: E402
from envmon.notifier import Notifier  # noqa: E402
from envmon.poller import Poller  # noqa: E402

sent = []
toast.show_toast = lambda t, b: (sent.append((t, b)) or True)

cfg = load_config()
print("URL:", cfg.get("url"))
state = AppState()
notifier = Notifier()
poller = Poller(cfg, state, notifier)
poller._poll_once()

rooms = {r.name: r for r in state.snapshot()}
ok = True
print("検出部屋:", list(rooms))
a = rooms.get("会議室A")
if a and a.latest:
    print(f"  会議室A temp={a.latest.temp} severity={a.severity.name}")
    ok &= abs(a.latest.temp - 35.2) < 1e-6
    ok &= a.severity == Severity.WARN
else:
    ok = False
    print("  会議室A が取得できていない")

print("発火トースト:", sent)
ok &= any("会議室A" in b for _, b in sent)

print("\n統合テスト:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
