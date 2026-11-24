"""応用例: チップではなく renderer で本体を自由に描く。

``@app.renderer`` に渡した関数が本体フレームを受け取り、任意の
CustomTkinter ウィジェットを自分で構築できる（チップでは足りない時に）。

    python -m taskwidget.examples.custom_render
"""
from __future__ import annotations

import time

import customtkinter as ctk

import taskwidget as tw
from taskwidget import theme


def main() -> None:
    app = tw.TaskbarWidget(title="Custom", dock="float")

    @app.renderer
    def draw(body):
        ctk.CTkLabel(body, text="⏱ " + time.strftime("%H:%M"),
                     font=theme.font(20, "bold"),
                     text_color=theme.TEXT).pack(padx=8, pady=4)
        ctk.CTkLabel(body, text=time.strftime("%Y-%m-%d (%a)"),
                     font=theme.font(11), text_color=theme.MUTED).pack()

    # renderer は再描画時に呼び直されるので、定期的に本体を作り直して更新。
    @app.every(1000)
    def tick():
        app.refresh()

    app.run()


if __name__ == "__main__":
    main()
