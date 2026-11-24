"""ログオン時自動起動の登録/解除（HKCU...\\Run）と単一起動ミューテックス."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "EnvMonitor"


def _exe_command() -> str:
    """自動起動に登録するコマンド文字列を返す.

    PyInstaller 凍結時は exe パス、ソース実行時は `pythonw script` を使う。
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # ソース実行: ウィンドウなしの pythonw でメインを起動
    pyw = Path(sys.executable).with_name("pythonw.exe")
    launcher = pyw if pyw.exists() else Path(sys.executable)
    script = Path(__file__).resolve().parent.parent / "run_envmon.py"
    return f'"{launcher}" "{script}"'


def is_registered() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError as e:
        log.debug("自動起動状態の確認失敗: %s", e)
        return False


def set_startup(enabled: bool) -> bool:
    """自動起動を登録/解除。成功で True。"""
    try:
        import winreg
        if enabled:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, _exe_command())
            log.info("自動起動を登録しました")
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                log.info("自動起動を解除しました")
            except FileNotFoundError:
                pass
        return True
    except OSError as e:
        log.error("自動起動の設定に失敗: %s", e)
        return False


class SingleInstance:
    """名前付きミューテックスで二重起動を防ぐ."""

    MUTEX_NAME = "Global\\EnvMonitor_SingleInstance_Mutex"

    def __init__(self):
        self._mutex = None
        self.already_running = False

    def acquire(self) -> bool:
        try:
            import win32api
            import win32event
            import winerror
            self._mutex = win32event.CreateMutex(None, False, self.MUTEX_NAME)
            if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
                self.already_running = True
                return False
            return True
        except Exception as e:  # pragma: no cover
            log.warning("単一起動チェックに失敗（続行）: %s", e)
            return True

    def release(self) -> None:
        if self._mutex is not None:
            try:
                import win32api
                win32api.CloseHandle(self._mutex)
            except Exception:
                pass
            self._mutex = None
