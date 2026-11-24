"""最小例: タスクバーに時計を出す。

    python -m taskwidget.examples.clock
"""
from __future__ import annotations

import time

import taskwidget as tw


def main() -> None:
    app = tw.TaskbarWidget(title="Clock", dock="taskbar")
    clock = app.chip("TIME", "--:--:--")

    @app.every(500)
    def tick():
        clock.update(value=time.strftime("%H:%M:%S"))

    app.run()


if __name__ == "__main__":
    main()
