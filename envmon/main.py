"""エントリポイント: 単一起動・UI/poller/tray の統合."""
from __future__ import annotations

import logging
import logging.handlers
import sys

import customtkinter as ctk

from . import startup
from .config import load_config, log_path
from .flyout import Flyout
from .model import AppState
from .notifier import Notifier
from .overlay_bridge import OverlayBridge, write_state as overlay_write_state
from .poller import Poller
from .settings_ui import SettingsWindow
from .tray import Tray
from .widget import DesktopWidget

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

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.withdraw()  # メインウィンドウは常に非表示（トレイ常駐）
        # タスクバー/Alt+Tab に出さない（＝「通知領域(トレイ)に居るだけ」のアプリにする）。
        # ツールウィンドウ属性を付けると、たとえ表示されてもタスクバーボタンを作らない。
        try:
            self.root.wm_attributes("-toolwindow", True)
        except Exception:
            pass

        self.flyout = Flyout(self.root, self.state, self.config,
                             on_room_click=self._open_settings_room,
                             on_settings=self._open_settings)
        self.widget = DesktopWidget(self.root, self.state, self.config,
                                    on_settings=self._open_settings)
        self.settings = SettingsWindow(self.root, self.config, self.state,
                                       self.notifier, on_saved=self._on_settings_saved)
        self.poller = Poller(self.config, self.state, self.notifier,
                             on_update=self._on_poll_update)
        self.overlay = OverlayBridge(self.config)
        self.tray = Tray(self.state,
                         on_open=self._req_toggle_flyout,
                         on_settings=self._req_open_settings,
                         on_refresh=self.poller.poll_now,
                         on_quit=self._req_quit,
                         on_widget=self._req_toggle_widget,
                         on_widget_reset=self._req_reset_widget)
        self._quitting = False

    # --- スレッド跨ぎのマーシャリング（tray/poller スレッド -> Tk main） ---
    def _req_toggle_flyout(self):
        self.root.after(0, self.flyout.toggle)

    def _req_open_settings(self):
        self.root.after(0, self._open_settings)

    def _req_toggle_widget(self):
        self.root.after(0, self.widget.toggle)

    def _req_reset_widget(self):
        self.root.after(0, self.widget.reset_position)

    def _req_quit(self):
        self.root.after(0, self.quit)

    def _on_poll_update(self):
        # overlay 用 state.json を書き出す（poller スレッドで実行。Tk 非依存）。
        overlay_write_state(self.state, self.config)
        self.root.after(0, self._apply_update)

    def _apply_update(self):
        self.tray.refresh()
        if getattr(self.flyout, "_visible", False):
            self.flyout.refresh()
        if getattr(self.widget, "_visible", False):
            self.widget.refresh()

    def _open_settings(self, room: str | None = None):
        self.flyout.hide()
        self.settings.open(room)

    def _open_settings_room(self, room: str):
        self._open_settings(room)

    def _on_settings_saved(self):
        self.poller.poll_now()
        self.tray.refresh()
        self.widget.refresh()
        self.widget.apply_enabled()

    def run(self):
        # 設定に沿って自動起動状態を同期
        if self.config.get("run_at_startup"):
            startup.set_startup(True)
        self.poller.start()
        self.overlay.start()
        self.widget.apply_enabled()
        self.tray.run_detached()
        log.info("EnvMonitor 起動")
        try:
            self.root.mainloop()
        finally:
            self._cleanup()

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        log.info("終了処理")
        self.root.quit()

    def _cleanup(self):
        try:
            self.overlay.stop()
        except Exception:
            pass
        try:
            self.poller.stop()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


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
