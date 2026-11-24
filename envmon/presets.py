"""すぐ使えるプリセット集（しきい値 / 状態ラベル）.

設定画面から1クリックで流し込めるよう、用途別の下限・上限をまとめておく。
値は (min, max)。None はその側を判定しない（＝通知しない）意味。
"""
from __future__ import annotations

# ---- 部屋のしきい値プリセット ----
# name -> {"temp": (lo, hi), "humid": (lo, hi), "hint": str}
# ※監視対象は気温・湿度のみ（電圧は監視しない）。
ROOM_PRESETS: list[tuple[str, dict]] = [
    ("快適な居室（人がいる部屋）", {
        "temp": (18.0, 28.0), "humid": (30.0, 70.0),
        "hint": "オフィスや自室など。暑すぎ・寒すぎ・乾燥しすぎを知らせます。",
    }),
    ("サーバー室・機器まわり", {
        "temp": (10.0, 30.0), "humid": (20.0, 70.0),
        "hint": "機器の過熱や結露しそうな高湿度を監視。",
    }),
    ("冷蔵・保冷（低温を保つ）", {
        "temp": (2.0, 8.0), "humid": (None, None),
        "hint": "冷蔵庫・保冷庫。温度が上がったら知らせます。",
    }),
    ("温室・植物（暖かく保つ）", {
        "temp": (15.0, 35.0), "humid": (40.0, 85.0),
        "hint": "植物用。冷え込みと乾燥を監視。",
    }),
    ("ゆるめ（よほどの時だけ）", {
        "temp": (5.0, 38.0), "humid": (15.0, 90.0),
        "hint": "通知は控えめ。極端なときだけ知らせます。",
    }),
    ("きっちり監視（狭め）", {
        "temp": (20.0, 26.0), "humid": (40.0, 60.0),
        "hint": "少しのズレでも気づきたい人向け。",
    }),
]

ROOM_PRESET_PLACEHOLDER = "プリセットから選ぶ…"


def room_preset(name: str) -> dict | None:
    for n, data in ROOM_PRESETS:
        if n == name:
            return data
    return None


# ---- 状態の呼び方プリセット ----
# 「異常」のような強い言葉を避けたい人向けに、トーン違いを用意。
LABEL_PRESETS: dict[str, dict[str, str]] = {
    "やわらかめ": {"ok": "正常", "warn": "気になる", "critical": "要チェック", "stale": "応答なし"},
    "ふつう": {"ok": "正常", "warn": "注意", "critical": "要確認", "stale": "応答なし"},
    "きっちり": {"ok": "正常", "warn": "警告", "critical": "異常", "stale": "停止"},
    "英語": {"ok": "OK", "warn": "Warn", "critical": "Alert", "stale": "No data"},
}

LABEL_PRESET_PLACEHOLDER = "プリセットから選ぶ…"

# config のデフォルトに使う既定ラベル（model.Severity.label と揃える）
DEFAULT_LABELS: dict[str, str] = dict(LABEL_PRESETS["ふつう"])
