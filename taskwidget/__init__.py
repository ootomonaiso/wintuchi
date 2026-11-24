"""taskwidget — Windows タスクバーに追従する小さなウィジェットをお手軽に作る。

Win11 はタスクバー内へウィジェットを埋め込む公式 API を廃止しているため、
本ライブラリは「タスクバー矩形を検出して、その上へ最前面オーバーレイを
重ねて追従させる」方式（公式系ツールと同じ作法）で“タスクバー常駐風”を実現する。

Quickstart::

    import taskwidget as tw

    app = tw.TaskbarWidget(title="Monitor")
    cpu = app.chip("CPU", "--")

    @app.every(1000)
    def tick():
        cpu.update(value="42%", status="ok")

    app.run()

依存: customtkinter（描画）。タスクバー検出は純 ctypes（Windows 専用）。
"""
from __future__ import annotations

from . import geometry, theme
from .chips import Chip
from .geometry import TaskbarInfo, find_taskbar, work_area
from .widget import TaskbarWidget

# 状態キー（status=...）を補完が効くよう定数でも公開
OK = "ok"
WARN = "warn"
CRITICAL = "critical"
STALE = "stale"
INFO = "info"

__version__ = "0.1.0"

__all__ = [
    "TaskbarWidget", "Chip", "TaskbarInfo", "find_taskbar", "work_area",
    "geometry", "theme",
    "OK", "WARN", "CRITICAL", "STALE", "INFO",
]
