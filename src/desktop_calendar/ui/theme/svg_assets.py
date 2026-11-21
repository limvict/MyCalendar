# coding: utf-8
"""把内联 SVG 落盘成缓存文件，供 QSS 的 ``image: url(...)`` 使用。

Qt 的样式表图片加载器**不支持 data: URI**（实测 svg / png 的
data URI 都不生效，只有文件路径能被加载），所以主题里的下拉箭头、
勾选标记这类小图标必须先写成文件再引用。按内容哈希复用，同一份
SVG 只落盘一次。

任何写盘失败（只读目录、权限不足）都返回空串，QSS 侧据此跳过
``image`` 声明——退化成"没有图标"，而不是整条样式失效。
"""

from __future__ import annotations

import hashlib
import os

from ...config.manager import get_logger
from ...utils.paths import get_app_data_dir

logger = get_logger()

_CACHE_DIRNAME = "theme_assets"


def cache_dir() -> str:
    return os.path.join(get_app_data_dir(), _CACHE_DIRNAME)


def write_asset(svg: str, *, directory: str | None = None) -> str:
    """把 SVG 写成缓存文件并返回文件路径；失败返回空串。"""
    if not svg:
        return ""
    target_dir = directory or cache_dir()
    digest = hashlib.sha1(svg.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(target_dir, f"icon_{digest}.svg")
    try:
        if not os.path.isfile(path):
            os.makedirs(target_dir, exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(svg)
            os.replace(tmp, path)
    except OSError as error:
        logger.debug("写入主题图标失败，跳过该图标: %s", error)
        return ""
    return path


def asset_url(svg: str, *, directory: str | None = None) -> str:
    """把 SVG 写成缓存文件并返回 ``url("path")``；失败返回空串。"""
    path = write_asset(svg, directory=directory)
    if not path:
        return ""
    return 'url("{}")'.format(path.replace("\\", "/"))


def image_declaration(uri: str) -> str:
    """返回安全的 ``image: ...;`` 片段；没有可用图标时返回空串。"""
    return f"image: {uri};" if uri else ""
