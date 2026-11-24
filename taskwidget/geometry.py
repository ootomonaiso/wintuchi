"""Windows タスクバーの座標検出（純 ctypes・依存ゼロ）.

Win11 はタスクバー内へウィジェットを埋め込む公式 API を廃止したため、
本ライブラリは「タスクバー矩形を検出し、その上へ最前面オーバーレイを重ねて
追従させる」方式を採る。ここではその配置に必要な幾何情報だけを提供する。

すべて Windows 専用。非 Windows や取得失敗時は None / 既定値を返すので、
呼び出し側は「取得できなければ float（任意位置）へフォールバック」できる。
"""
from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# SystemParametersInfo の定数
_SPI_GETWORKAREA = 0x0030


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


@dataclass(frozen=True)
class TaskbarInfo:
    """検出したタスクバーの配置情報.

    Attributes:
        edge: タスクバーが画面のどの辺にあるか（"bottom"/"top"/"left"/"right"）。
        horizontal: 水平配置（上辺/下辺）なら True。追従配置が自然に効くのは水平時。
        left/top/right/bottom: タスクバー矩形（スクリーン座標）。
        tray_left: システムトレイ(TrayNotifyWnd)の左端 X。無ければ right と同値。
        height/width: タスクバーの縦横サイズ。
    """

    edge: str
    horizontal: bool
    left: int
    top: int
    right: int
    bottom: int
    tray_left: int

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def width(self) -> int:
        return self.right - self.left


def work_area(fallback: tuple[int, int, int, int] = (0, 0, 1920, 1040)
              ) -> tuple[int, int, int, int]:
    """プライマリモニタの作業領域 (left, top, right, bottom)（タスクバー除く）.

    float 配置の初期位置（右下など）を決めるのに使う。
    """
    if not IS_WINDOWS:
        return fallback
    try:
        rect = _RECT()
        ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception as e:  # pragma: no cover
        log.debug("作業領域の取得に失敗: %s", e)
        return fallback


def find_taskbar() -> Optional[TaskbarInfo]:
    """タスクバー(Shell_TrayWnd)とトレイ(TrayNotifyWnd)から配置情報を得る.

    取得できない／明らかにタスクバーらしくない場合は None。
    自動的に隠れる設定でも矩形自体は返るが、edge/horizontal で呼び出し側が判断する。
    """
    if not IS_WINDOWS:
        return None
    try:
        u = ctypes.windll.user32
        tray = u.FindWindowW("Shell_TrayWnd", None)
        if not tray:
            return None
        tr = _RECT()
        u.GetWindowRect(tray, ctypes.byref(tr))
        screen_w = u.GetSystemMetrics(0)
        screen_h = u.GetSystemMetrics(1)
        width = tr.right - tr.left
        height = tr.bottom - tr.top
        horizontal = width >= height

        # 水平配置なら画面幅の過半を占めるはず。満たさなければタスクバーと見なさない。
        if horizontal and width < screen_w * 0.6:
            return None

        if horizontal:
            edge = "bottom" if tr.top >= screen_h / 2 else "top"
        else:
            edge = "right" if tr.left >= screen_w / 2 else "left"

        tray_left = tr.right
        notify = u.FindWindowExW(tray, 0, "TrayNotifyWnd", None)
        if notify:
            nr = _RECT()
            u.GetWindowRect(notify, ctypes.byref(nr))
            tray_left = nr.left

        return TaskbarInfo(
            edge=edge, horizontal=horizontal,
            left=tr.left, top=tr.top, right=tr.right, bottom=tr.bottom,
            tray_left=tray_left,
        )
    except Exception as e:  # pragma: no cover
        log.debug("タスクバー矩形の取得に失敗: %s", e)
        return None


def system_uses_light_theme() -> bool:
    """Windows の「アプリ/システムのモード」がライトかを返す（既定: False=ダーク）.

    タスクバーの地色をなるべく合わせたい時の目安に使う。レジストリ
    HKCU\\...\\Themes\\Personalize\\SystemUsesLightTheme を読む。
    """
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        val, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
        winreg.CloseKey(key)
        return bool(val)
    except Exception:
        return False
