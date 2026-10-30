# coding: utf-8
"""轻量级 i18n。三级回退：当前语言 → zh_CN → key 本身。

源码级 tr("字面量") key 校验见 scripts/check_i18n.py；
本模块同时暴露 validate_keys() 供测试 / CI 使用。
"""
import re                                      # ← 新增
from typing import Callable, List, Optional

from desktop_calendar.utils.logging_setup import get_logger
from desktop_calendar.config.translations import LANGUAGES, ZH_CN

logger = get_logger()

_DEFAULT_LANG = "zh_CN"
_current_lang: str = _DEFAULT_LANG
_listeners: List[Callable[[str], None]] = []
_current_table: dict = ZH_CN

def set_language(lang: Optional[str]) -> None:
    global _current_lang, _current_table
    if lang in LANGUAGES:
        new_lang = lang
        table = LANGUAGES[new_lang].get("table")
        if table is None:
            logger.warning(
                f"语言 {new_lang!r} 的 table 缺失，回退到 {_DEFAULT_LANG}")
            new_lang = _DEFAULT_LANG
            table = ZH_CN
    else:
        logger.warning(f"未知语言 {lang!r}，回退到 {_DEFAULT_LANG}")
        new_lang = _DEFAULT_LANG
        table = ZH_CN

    if new_lang == _current_lang:
        return
    _current_lang = new_lang
    _current_table = table

    for cb in list(_listeners):
        try:
            cb(new_lang)
        except Exception:
            logger.exception(f"语言切换监听者执行失败 lang={new_lang!r}")


def get_language() -> str:
    return _current_lang


def on_language_changed(cb: Callable[[str], None]) -> None:
    """注册语言切换监听者。重复注册不会重复入列。"""
    if cb not in _listeners:
        _listeners.append(cb)


def off_language_changed(cb: Callable[[str], None], *_args) -> None:
    """注销语言切换监听者；未注册时不报错（幂等）。"""
    try:
        _listeners.remove(cb)
    except ValueError:
        pass


def tr(key: str, **kwargs) -> str:
    """翻译。三级回退：当前语言 → zh_CN → key 本身。"""
    text = _current_table.get(key)
    if text is None and _current_table is not ZH_CN:
        text = ZH_CN.get(key)
    if text is None:
        logger.debug(f"翻译缺失 key={key!r} lang={_current_lang!r}")
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # ValueError：语言包文本含未配对 { / } 等格式串语法错误，
            # 例如手写翻译时漏写右花括号。validate_keys 只比对占位符集合，
            # 不校验格式串语法，必须在运行期兜底。
            logger.warning(
                f"翻译格式化失败 key={key!r} kwargs={kwargs!r}")
            return text
    return text


def available_languages() -> list[tuple[str, str]]:
    return [(code, meta["name"]) for code, meta in LANGUAGES.items()]

# ===================== key 一致性校验 =====================
# 只匹配命名占位符；本项目翻译文本不使用 {{ }} 转义，故不处理该情况。
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _placeholders(text: str) -> set:
    return set(_PLACEHOLDER_RE.findall(text or ""))


def validate_keys(*, strict: bool = False) -> dict:
    """检查各非默认语言相对 zh_CN 的一致性。

    返回 {code: {"missing": [...], "extra": [...],
                 "placeholder_mismatch": {key: {lang: [...], ...}}}}

    strict=True 时，只要存在不一致就抛 RuntimeError；用于测试 / CI。
    """
    base_keys = set(ZH_CN)
    report: dict = {}
    for code, meta in LANGUAGES.items():
        if code == _DEFAULT_LANG:
            continue
        table = meta.get("table") or {}
        keys = set(table)
        missing = sorted(base_keys - keys)
        extra = sorted(keys - base_keys)

        mismatch: dict = {}
        for key in sorted(base_keys & keys):
            zh_ph = _placeholders(ZH_CN[key])
            other_ph = _placeholders(table[key])
            if zh_ph != other_ph:
                mismatch[key] = {
                    _DEFAULT_LANG: sorted(zh_ph),
                    code: sorted(other_ph),
                }

        if missing or extra or mismatch:
            report[code] = {
                "missing": missing,
                "extra": extra,
                "placeholder_mismatch": mismatch,
            }
            logger.warning(
                f"语言 {code!r} 与 zh_CN 的 key 不一致："
                f"missing={len(missing)} extra={len(extra)} "
                f"placeholder_mismatch={len(mismatch)}")
    if strict and report:
        raise RuntimeError(f"语言 key 不一致：{report}")
    return report