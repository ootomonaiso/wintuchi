"""システムトレイアイコン（pystray）."""
from __future__ import annotations

import logging
from typing import Callable

import pystray
from pystray import Menu, MenuItem

from . import icons
from .model import AppState, Severity

log = logging.getLogger(__name__)


class Tray:
    def __init__(self, state: AppState,
                 on_open: Callable[[], None],
                 on_settings: Callable[[], None],
                 on_refresh: Callable[[], None],
                 on_quit: Callable[[], None],
                 on_widget: Callable[[], None],
                 on_widget_reset: Callable[[], None]):
        self.state = state
        self._on_open = on_open
        self._on_settings = on_settings
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._on_widget = on_widget
        self._on_widget_reset = on_widget_reset
        self._severity = Severity.OK

        menu = Menu(
            MenuItem("開く", self._handle_open, default=True),
            MenuItem("ウィジェット表示/非表示", self._handle_widget),
            MenuItem("ウィジェット位置をリセット", self._handle_widget_reset),
            MenuItem("設定…", self._handle_settings),
            MenuItem("今すぐ更新", self._handle_refresh),
            Menu.SEPARATOR,
            MenuItem("終了", self._handle_quit),
        )
        self.icon = pystray.Icon(
            "EnvMonitor",
            icon=icons.make_icon(Severity.OK),
            title="環境モニタ",
            menu=menu,
        )

    # pystray のコールバックは別スレッド。UI操作は呼び出し先で after() マーシャリングする。
    def _handle_open(self, icon=None, item=None):
        self._on_open()

    def _handle_widget(self, icon=None, item=None):
        self._on_widget()

    def _handle_widget_reset(self, icon=None, item=None):
        self._on_widget_reset()

    def _handle_settings(self, icon=None, item=None):
        self._on_settings()

    def _handle_refresh(self, icon=None, item=None):
        self._on_refresh()

    def _handle_quit(self, icon=None, item=None):
        self._on_quit()

    def run_detached(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass

    def refresh(self) -> None:
        """最悪 severity に応じてアイコン色とツールチップを更新."""
        sev = self.state.worst_severity()
        if sev != self._severity:
            self._severity = sev
            try:
                self.icon.icon = icons.make_icon(sev)
            except Exception as e:
                log.debug("アイコン更新失敗: %s", e)
        # ツールチップに概況
        with self.state.lock:
            n_rooms = len(self.state.rooms)
            alerts = sum(1 for r in self.state.rooms.values() if r.severity != Severity.OK)
        tip = f"環境モニタ — {n_rooms}部屋"
        if alerts:
            tip += f" / {alerts}件のアラート"
        else:
            tip += " / 正常"
        try:
            self.icon.title = tip
        except Exception:
            pass
