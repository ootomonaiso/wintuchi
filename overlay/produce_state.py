"""Phase2 連携デモ: Python が overlay の表示内容(state.json)を決めて書き出す。

責任分離の実証:
  - Python が「何を・どの色で」出すかを決める（しきい値で緑/橙/赤に色分け）。
  - Rust の overlay はこの JSON を読んで描くだけ（中身を解釈しない）。

実行（venv の python 推奨。psutil を使う）:
    C:\\Users\\ootom\\envmon-venv\\Scripts\\python.exe overlay\\produce_state.py

overlay 側は state.json があればそれを優先表示（無ければ内蔵の CPU/MEM）。
後で EnvMonitor 本体（温度/湿度センサ）に差し替えるのも build() を書き換えるだけ。
"""
from __future__ import annotations

import json
import os
import time

STATE_PATH = r"C:/Users/ootom/envmon-overlay.state.json"
INTERVAL_SEC = 1.0


def color_for(pct: float) -> str:
    """使用率を緑→橙→赤に色分け（色の決定は Python の責任）。"""
    if pct >= 85:
        return "#E24C4C"  # 赤
    if pct >= 60:
        return "#E8A33D"  # 橙
    return "#3BA55D"      # 緑


def build() -> dict:
    """overlay に出すチップ列を作る。ここを差し替えれば表示内容を自由に変えられる。"""
    import psutil

    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    return {
        "chips": [
            {"label": "CPU", "value": f"{cpu:.0f}%", "fg": color_for(cpu)},
            {"label": "RAM", "value": f"{mem:.0f}%", "fg": color_for(mem)},
        ]
    }


def write_atomic(path: str, data: dict) -> None:
    """単一書き手・原子的書き込み（os.replace）。読み手は常に完全な JSON を見る。"""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def main() -> None:
    import psutil

    psutil.cpu_percent(interval=None)  # 初回は 0 を返すので空読みでならす
    print(f"writing {STATE_PATH} every {INTERVAL_SEC}s ... (Ctrl+C で停止)")
    try:
        while True:
            write_atomic(STATE_PATH, build())
            time.sleep(INTERVAL_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        # 終了時に state.json を消すと overlay は内蔵 CPU/MEM 表示へ戻る。
        try:
            os.remove(STATE_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    main()
