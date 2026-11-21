# coding: utf-8
"""下载重试判定：哪些网络/磁盘错误值得重试一次。"""

from __future__ import annotations

import http.client
import socket
from urllib.error import URLError

from .update_errors import _IncompleteDownload

_ENOSPC = 28


_RETRYABLE_WINERRORS = frozenset({10053, 10054, 10060, 10061})


def _iter_exc_chain(exc: BaseException):
    seen: set = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def _is_retryable_network_error(exc: BaseException) -> bool:
    for e in _iter_exc_chain(exc):
        if isinstance(
            e,
            (
                ConnectionResetError,
                ConnectionAbortedError,
                TimeoutError,
                socket.timeout,
                _IncompleteDownload,
                http.client.IncompleteRead,
            ),
        ):
            return True
        if getattr(e, "winerror", None) in _RETRYABLE_WINERRORS:
            return True
        if isinstance(e, URLError):
            reason = getattr(e, "reason", None)
            if isinstance(reason, str):
                low = reason.lower()
                if any(
                    t in low
                    for t in (
                        "reset",
                        "aborted",
                        "timed out",
                        "connection closed",
                        "connection aborted",
                    )
                ):
                    return True
    return False
