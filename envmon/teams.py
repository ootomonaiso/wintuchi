"""Teams Webhook (Power Automate) への送信.

Power Automate の「HTTP 要求の受信時」/「Teams の Webhook 要求受信時」トリガで
受け取れるペイロードを送る。標準の Workflows チャネル投稿テンプレートが解釈できる
Adaptive Card 形式に加え、カスタムフローが読みやすい flat な "data" も同梱する。
"""
from __future__ import annotations

import logging

import requests

from .model import Severity

log = logging.getLogger(__name__)

_SEV_STYLE = {
    Severity.OK: ("good", "✅"),
    Severity.WARN: ("warning", "⚠️"),
    Severity.CRITICAL: ("attention", "🚨"),
    Severity.STALE: ("accent", "📴"),
}


def build_payload(room: str, metric: str, message: str, severity: Severity,
                  value, timestamp: str, status_label: str | None = None) -> dict:
    style, emoji = _SEV_STYLE.get(severity, ("default", "ℹ️"))
    # 表示用の状態名（設定の labels を優先、未指定なら既定）
    sev_label = status_label if (status_label and status_label.strip()) else severity.label
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"{emoji} 環境モニタ通知",
                "weight": "Bolder",
                "size": "Medium",
                "color": style,
            },
            {
                "type": "TextBlock",
                "text": message,
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "部屋", "value": room},
                    {"title": "項目", "value": metric},
                    {"title": "状態", "value": sev_label},
                    {"title": "時刻", "value": timestamp},
                ],
            },
        ],
    }
    return {
        # 標準 Workflows テンプレート（チャネル投稿）が解釈する形式
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
        # カスタムフローが triggerBody()?['data'] で読める素データ
        "data": {
            "room": room,
            "metric": metric,
            "severity": sev_label,
            "severity_level": int(severity),
            "value": value,
            "message": message,
            "timestamp": timestamp,
        },
    }


def send(webhook_url: str, payload: dict, timeout: int = 10, retries: int = 2) -> bool:
    """Webhook へ POST。成功で True。失敗時はリトライ。"""
    if not webhook_url:
        return False
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=timeout)
            # Power Automate は 200/202 を返すことが多い
            if resp.status_code in (200, 201, 202):
                return True
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.RequestException as e:
            last_err = str(e)
    log.warning("Teams送信失敗: %s", last_err)
    return False
