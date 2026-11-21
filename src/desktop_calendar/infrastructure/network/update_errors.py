# coding: utf-8
"""更新流程内部异常：下载、校验、限速与安装器启动。"""

from __future__ import annotations


class _DownloadCancelled(Exception):
    pass


class _ShaMismatch(IOError):
    pass


class _IncompleteDownload(IOError):
    pass


class _SlowDownload(IOError):
    pass


class _InstallerLaunchError(IOError):
    pass
