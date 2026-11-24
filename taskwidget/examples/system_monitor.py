"""実用例: CPU/メモリ使用率をタスクバーに常時表示する。

psutil があれば実測、無ければダミー値で動く（ライブラリ単体で試せるように）。
float 位置を記憶するので、浮遊モードに切り替えてドラッグすると次回も同じ場所に出る。

    python -m taskwidget.examples.system_monitor
"""
from __future__ import annotations

import random
from pathlib import Path

import taskwidget as tw

try:
    import psutil
except ImportError:  # psutil 未インストールでも動くフォールバック
    psutil = None


def read_cpu() -> float:
    return psutil.cpu_percent() if psutil else random.uniform(5, 95)


def read_mem() -> float:
    return psutil.virtual_memory().percent if psutil else random.uniform(30, 80)


def level(pct: float) -> str:
    return "critical" if pct >= 90 else "warn" if pct >= 70 else "ok"


def main() -> None:
    state = Path.home() / ".taskwidget" / "sysmon.json"
    app = tw.TaskbarWidget(title="System", dock="taskbar", state_file=state)

    cpu = app.gauge("CPU", "--")
    mem = app.gauge("MEM", "--")

    @app.every(1000)
    def tick():
        c, m = read_cpu(), read_mem()
        cpu.update(value=f"{c:.0f}%", status=level(c), frac=c / 100)
        mem.update(value=f"{m:.0f}%", status=level(m), frac=m / 100)

    app.run()


if __name__ == "__main__":
    main()
