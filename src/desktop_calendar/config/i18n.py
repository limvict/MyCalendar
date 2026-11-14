# coding: utf-8
"""轻量级文案查表。

单语言（简体中文）项目：tr() 直接查 ZH_CN，缺失返回 key 本身，
便于开发期发现漏配。不做运行时语言切换，不维护监听器。

源码级 tr("字面量") key 校验见 scripts/check_i18n.py。
"""
from desktop_calendar.utils.logging_setup import get_logger
from desktop_calendar.config.translations import ZH_CN

logger = get_logger()

_format_failures: set = set()


def get_format_failures() -> frozenset:
    """返回运行期 tr() 格式化失败的 key 集合。测试 / 诊断用。"""
    return frozenset(_format_failures)


def clear_format_failures() -> None:
    _format_failures.clear()


def tr(key: str, **kwargs) -> str:
    """查文案。缺失返回 key 本身（开发期可见）。"""
    text = ZH_CN.get(key)
    if text is None:
        logger.debug(f"翻译缺失 key={key!r}")
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError) as e:
            if isinstance(e, KeyError):
                logger.warning(
                    "翻译格式化失败 key=%r kwargs=%r 缺失参数=%s",
                    key, kwargs, e.args[0] if e.args else "?")
            else:
                logger.warning(
                    "翻译格式化失败 key=%r kwargs=%r 格式串语法错: %s",
                    key, kwargs, e)
            _format_failures.add(key)
            return text
    return text