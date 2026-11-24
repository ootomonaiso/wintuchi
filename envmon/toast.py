"""Windows トースト通知ラッパ（windows-toasts）.

windows-toasts が無い/初期化失敗の環境でも落ちないようにフォールバックする。
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_toaster = None
_available = False

try:
    from windows_toasts import Toast, WindowsToaster

    _toaster = WindowsToaster("環境モニタ")
    _available = True
except Exception as e:  # pragma: no cover - 環境依存
    log.warning("windows-toasts 初期化失敗。トーストは無効: %s", e)


def available() -> bool:
    return _available


def show_toast(title: str, body: str) -> bool:
    """トーストを表示。成功で True。"""
    if not _available or _toaster is None:
        log.info("[toast無効] %s / %s", title, body)
        return False
    try:
        toast = Toast()
        toast.text_fields = [title, body]
        _toaster.show_toast(toast)
        return True
    except Exception as e:  # pragma: no cover
        log.error("トースト表示失敗: %s", e)
        return False
