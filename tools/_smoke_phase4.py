"""Phase4 スモーク: validate / httpconfig を実起動せず検証。"""
import json
import sys
import threading
import time
import urllib.request

sys.path.insert(0, ".")
from envmon import validate  # noqa: E402


def test_validate():
    bad = {
        "poll_interval_sec": "abc",
        "quiet_hours": {"start": "99:99", "end": "07:00", "enabled": "yes"},
        "rooms": {"A": {"temp": {"min": 30, "max": 10},
                        "lux_gate": {"mode": "weird", "value": "7"}}},
        "widget": {"dock": "nope", "opacity": 5,
                   "items": [{"room": "A", "metric": "temp"}, {"bad": 1}]},
        "overlay": {"enabled": "yes"},
    }
    clean, warn = validate.normalize(bad)
    assert clean["poll_interval_sec"] == 30, clean["poll_interval_sec"]
    assert clean["quiet_hours"]["start"] == "22:00", clean["quiet_hours"]["start"]
    assert clean["quiet_hours"]["enabled"] is True
    assert clean["rooms"]["A"]["temp"] == {"min": 10.0, "max": 30.0}
    assert clean["rooms"]["A"]["lux_gate"]["mode"] == "off"
    assert clean["widget"]["dock"] == "taskbar"
    assert clean["widget"]["opacity"] == 1.0
    assert clean["widget"]["items"] == [{"room": "A", "metric": "temp"}]
    assert clean["overlay"]["enabled"] is True
    assert validate.normalize(None)[0]["poll_interval_sec"] == 30
    print("validate OK; warnings:", warn)


class FakeState:
    def __init__(self):
        self.lock = threading.RLock()
        self.rooms = {}
        self.last_poll_ok = None
        self.last_poll_error = None


class FakeConfig:
    def __init__(self):
        self._data = {"url": "http://x", "rooms": {"会議室A": {}},
                      "sensors": {"1": "倉庫"}, "widget": {"items": []},
                      "overlay": {"enabled": True, "exe": ""}}
        self.applied = None

    def snapshot(self):
        import copy
        return copy.deepcopy(self._data)

    def replace(self, data):
        self.applied = data


def test_http():
    from envmon.httpconfig import ConfigServer
    cfg = FakeConfig()
    applied = {}

    def on_apply(clean):
        applied["clean"] = clean

    srv = ConfigServer(cfg, FakeState(), on_apply)
    srv.start()
    try:
        base = srv.url.rsplit("/?", 1)[0]
        tok = srv.token
        # GET / (HTML + bootstrap 注入)
        html = urllib.request.urlopen(srv.url).read().decode("utf-8")
        assert "window.__BOOT__ =" in html, "bootstrap 未注入"
        assert tok in html
        # GET /config
        c = json.loads(urllib.request.urlopen(f"{base}/config?t={tok}").read())
        assert c["url"] == "http://x"
        # GET /status (既知の部屋 union)
        s = json.loads(urllib.request.urlopen(f"{base}/status?t={tok}").read())
        assert set(s["rooms"]) == {"会議室A", "倉庫"}, s["rooms"]
        # 認証なし -> 403
        try:
            urllib.request.urlopen(f"{base}/config")
            assert False, "トークン無しが通った"
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # POST /config
        body = json.dumps({"poll_interval_sec": "bad", "overlay": {"enabled": True}}).encode()
        req = urllib.request.Request(f"{base}/config?t={tok}", data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        r = json.loads(urllib.request.urlopen(req).read())
        assert r["ok"] is True, r
        assert applied["clean"]["poll_interval_sec"] == 30
        print("http OK; status.rooms =", s["rooms"])
    finally:
        srv.stop()


if __name__ == "__main__":
    test_validate()
    test_http()
    print("ALL PASS")
