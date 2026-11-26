"""エントリポイント: 単一起動・ヘッドレス（poller / tray / 設定HTTP / overlay）.

UI（表示）は Rust 製オーバーレイ（別プロセス）が担い、設定はローカル HTTP の
HTML ダッシュボードで行う。この Python プロセスは GUI ツールキットに依存しない。
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import webbrowser

from . import startup
from .config import load_config, log_path
from .httpconfig import ConfigServer
from .model import AppState
from .notifier import Notifier
from .overlay_bridge import OverlayBridge, write_state as overlay_write_state
from .poller import Poller
from .tray import Tray

log = logging.getLogger(__name__)


def _setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(
        log_path(), maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # コンソールにも（ソース実行時のデバッグ用）
    if sys.stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        root.addHandler(sh)


class App:
    def __init__(self):
        self.config = load_config()
        self.state = AppState()
        self.notifier = Notifier()
        self._overlay_visible = True
        self._stop = threading.Event()

        self.poller = Poller(self.config, self.state, self.notifier,
                             on_update=self._on_poll_update)
        self.overlay = OverlayBridge(self.config)
        # 設定用ローカル HTTP（Tk 設定画面の後継。tray「設定」からブラウザで開く）
        self.httpserver = ConfigServer(self.config, self.state, self._apply_web_config)
        self.tray = Tray(self.state,
                         on_toggle=self._toggle_overlay,
                         on_settings=self._open_web_settings,
                         on_refresh=self.poller.poll_now,
                         on_quit=self._req_quit)

    # --- tray/poller/HTTP スレッドから直接呼ばれる（Tk 非依存なのでマーシャリング不要）---
    def _on_poll_update(self):
        overlay_write_state(self.state, self.config, visible=self._overlay_visible)
        self.tray.refresh()

    def _toggle_overlay(self):
        """オーバーレイの表示/非表示を切り替える（state.json の visible を書き換え）。"""
        self._overlay_visible = not self._overlay_visible
        overlay_write_state(self.state, self.config, visible=self._overlay_visible)
        log.info("オーバーレイ表示: %s", self._overlay_visible)

    def _open_web_settings(self):
        """tray「設定」: ローカル HTTP の設定ダッシュボードをブラウザで開く。"""
        try:
            webbrowser.open(self.httpserver.url)
        except Exception:
            log.exception("設定ページを開けませんでした")

    def _apply_web_config(self, clean: dict) -> None:
        """HTML ダッシュボードからの保存を適用する（HTTP スレッドから呼ばれる）。"""
        startup.set_startup(bool(clean.get("run_at_startup", False)))
        self.config.replace(clean)
        self.poller.poll_now()          # → _on_poll_update が state.json を書き直す
        self.overlay.apply_enabled()
        self.tray.refresh()

    def _req_quit(self):
        self._stop.set()

    def run(self):
        # 設定に沿って自動起動状態を同期
        if self.config.get("run_at_startup"):
            startup.set_startup(True)
        self.poller.start()
        self.overlay.start()
        self.httpserver.start()
        self.tray.run_detached()
        log.info("EnvMonitor 起動（ヘッドレス）")
        try:
            self._stop.wait()
        finally:
            self._cleanup()

    def _cleanup(self):
        for name, fn in (("httpserver", self.httpserver.stop),
                         ("overlay", self.overlay.stop),
                         ("poller", self.poller.stop),
                         ("tray", self.tray.stop)):
            try:
                fn()
            except Exception:
                log.debug("%s の停止で例外", name, exc_info=True)


def main() -> int:
    _setup_logging()
    instance = startup.SingleInstance()
    if not instance.acquire():
        log.warning("既に起動しています。終了します。")
        return 0
    try:
        App().run()
    finally:
        instance.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
