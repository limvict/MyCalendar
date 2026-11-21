"""Asynchronous client for the UAPIS random saying endpoint."""

from __future__ import annotations

import json
from collections.abc import Callable

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ...config.manager import get_logger

logger = get_logger()
_ENDPOINT = "https://uapis.cn/api/v1/saying/random"
_TIMEOUT_MS = 8_000
_MAX_TEXT_LENGTH = 500


class SidebarServices(QObject):
    """Fetch optional sidebar data without blocking the GUI thread."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._replies: set[QNetworkReply] = set()
        self._stopped = False

    def fetch(
        self,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        if self._stopped:
            on_error("网络服务已关闭")
            return

        request = QNetworkRequest(QUrl(_ENDPOINT))
        request.setTransferTimeout(_TIMEOUT_MS)
        reply = self._manager.get(request)
        self._replies.add(reply)

        def finish() -> None:
            self._replies.discard(reply)
            if self._stopped:
                reply.deleteLater()
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                error = reply.errorString()
                logger.warning("UAPIS 随机一言请求失败: %s", error)
                reply.deleteLater()
                on_error(error)
                return
            try:
                payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                result = self._parse_saying(payload)
            except (
                KeyError,
                TypeError,
                ValueError,
                UnicodeDecodeError,
                OverflowError,
            ) as error:
                logger.warning("UAPIS 随机一言响应无效: %s", error)
                reply.deleteLater()
                on_error(str(error))
                return
            reply.deleteLater()
            on_success(result)

        reply.finished.connect(finish)

    @staticmethod
    def _parse_saying(payload) -> str:
        if isinstance(payload, dict):
            value = payload.get("content") or payload.get("text")
            source = next(
                (
                    payload.get(key)
                    for key in ("source", "author", "from", "origin")
                    if isinstance(payload.get(key), str) and payload.get(key).strip()
                ),
                None,
            )
        else:
            value = payload
        if not isinstance(value, str) or not value.strip():
            raise ValueError("UAPIS 未返回可显示的一言")
        text = value.strip()[:_MAX_TEXT_LENGTH]
        if isinstance(payload, dict) and isinstance(source, str):
            text = f"{text}\n— {source.strip()[:80]}"
        return text

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        replies = tuple(self._replies)
        self._replies.clear()
        for reply in replies:
            reply.abort()
