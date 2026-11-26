"""設定用ローカル HTTP サーバ（Tk 設定画面の後継）.

tray「設定」→ ブラウザで ``settings.html`` を開いて設定を編集する。
Tk を使わずに「CodeZeno 的な親切ダッシュボード」を提供するのが狙い。

セキュリティ: ``127.0.0.1`` にのみバインドし、起動毎のランダムトークンを
URL に付与。トークンの無いリクエストは 403（ローカル他プロセスからの
POST を軽く防ぐ）。

エンドポイント:
  GET  /?t=TOKEN      … settings.html（TOKEN と presets を注入して配信）
  GET  /config?t=...  … 現在の config.json を返す
  POST /config?t=...  … 検証・正規化して保存し、poller に即時反映
  GET  /status?t=...  … 接続状態・既知の部屋一覧（ダッシュボード表示用）
  GET  /test?t=...&url=…&timeout=… … サーバ側で URL を叩いて結果を返す
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import presets
from .validate import normalize

log = logging.getLogger(__name__)

_HTML_PATH = Path(__file__).resolve().parent / "settings.html"


class _Handler(BaseHTTPRequestHandler):
    server: "ConfigServer"  # type: ignore[assignment]

    # アクセスログは logging へ（標準エラーを汚さない）
    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("httpconfig %s", fmt % args)

    # --- ヘルパ ---
    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def _authed(self) -> bool:
        tok = self._query().get("t", [""])[0]
        return secrets.compare_digest(tok, self.server.token)

    def _send_json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _forbidden(self) -> None:
        self.send_response(403)
        self.end_headers()
        self.wfile.write(b"forbidden")

    # --- GET ---
    def do_GET(self) -> None:  # noqa: N802 (http.server 規約)
        if not self._authed():
            return self._forbidden()
        route = urlparse(self.path).path
        if route == "/":
            return self._serve_page()
        if route == "/config":
            return self._send_json(self.server.config.snapshot())
        if route == "/status":
            return self._send_json(self.server.status_payload())
        if route == "/test":
            return self._serve_test()
        self.send_response(404)
        self.end_headers()

    def _serve_page(self) -> None:
        try:
            html = _HTML_PATH.read_text(encoding="utf-8")
        except OSError as e:
            log.error("settings.html を読めません: %s", e)
            return self._send_json({"error": "settings.html not found"}, 500)
        inject = {
            "token": self.server.token,
            "roomPresets": [{"name": n, **d} for n, d in presets.ROOM_PRESETS],
            "labelPresets": presets.LABEL_PRESETS,
        }
        html = html.replace(
            "/*__BOOTSTRAP__*/",
            "window.__BOOT__ = " + json.dumps(inject, ensure_ascii=False) + ";")
        self._send_html(html)

    def _serve_test(self) -> None:
        q = self._query()
        url = q.get("url", [""])[0].strip()
        timeout = 5
        try:
            timeout = max(1, int(float(q.get("timeout", ["5"])[0])))
        except (TypeError, ValueError):
            pass
        if not url:
            return self._send_json({"ok": False, "msg": "URL を入力してください"})
        self._send_json(_run_connection_test(url, timeout))

    # --- POST ---
    def do_POST(self) -> None:  # noqa: N802
        if not self._authed():
            return self._forbidden()
        if urlparse(self.path).path != "/config":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            return self._send_json({"ok": False, "error": f"不正なJSON: {e}"}, 400)
        clean, warnings = normalize(data)
        try:
            self.server.on_apply(clean)
        except Exception:
            log.exception("設定の適用に失敗")
            return self._send_json({"ok": False, "error": "適用に失敗しました"}, 500)
        log.info("設定をHTMLから保存（警告 %d件）", len(warnings))
        self._send_json({"ok": True, "warnings": warnings})


def _run_connection_test(url: str, timeout: int) -> dict[str, Any]:
    from .poller import latest_per_sensor, parse_records
    try:
        import requests
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        latest = latest_per_sensor(parse_records(resp.text))
        n = len(latest)
        if n:
            return {"ok": True, "n": n, "msg": f"接続OK — {n} 台のセンサを受信しました"}
        return {"ok": False, "n": 0, "msg": "つながりましたが、データが空でした"}
    except Exception as e:  # requests/parse いずれの失敗も拾う
        return {"ok": False, "msg": f"つながりません（{str(e)[:60]}）"}


class ConfigServer(ThreadingHTTPServer):
    """設定ダッシュボードを配信するローカル HTTP サーバ。

    config / on_apply / state を保持し、ハンドラから参照する。
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config, state, on_apply: Callable[[dict], None]):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.config = config
        self.state = state
        self.on_apply = on_apply
        self.token = secrets.token_urlsafe(16)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self.server_address[0], self.server_address[1]
        return f"http://{host}:{port}/?t={self.token}"

    def status_payload(self) -> dict[str, Any]:
        """ダッシュボードの接続バナー＋既知の部屋一覧。"""
        st = self.state
        cfg = self.config.snapshot()
        rooms = set(cfg.get("rooms", {}))
        rooms |= set(cfg.get("sensors", {}).values())
        last_ok = last_err = None
        try:
            with st.lock:
                rooms |= set(st.rooms)
                last_ok = st.last_poll_ok
                last_err = st.last_poll_error
        except Exception:
            pass
        return {
            "last_ok": last_ok.strftime("%H:%M:%S") if last_ok else None,
            "error": str(last_err) if last_err else None,
            "rooms": sorted(rooms),
        }

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.serve_forever, name="httpconfig", daemon=True)
        self._thread.start()
        log.info("設定サーバを起動: %s", self.url)

    def stop(self) -> None:
        try:
            self.shutdown()
            self.server_close()
        except Exception:
            pass
