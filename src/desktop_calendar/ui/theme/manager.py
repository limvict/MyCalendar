# coding: utf-8
"""ThemeManager：当前主题 Bundle + 切换/持久化。"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from desktop_calendar.config.manager import ConfigManager, get_logger
from desktop_calendar.config.constants import (
    DEFAULT_THEME, THEME_PRESETS, THEME_LIGHT,
)
from .bundle import ThemeBundle, build_bundle

logger = get_logger()


class ThemeManager(QObject):
    theme_changed = pyqtSignal(object)   # ThemeBundle

    def __init__(self, config: ConfigManager):
        super().__init__()
        self._config = config
        self._switching = False
        name = self._resolve_initial()
        try:
            self._current: ThemeBundle = build_bundle(name, self._load(name))
        except Exception as e:
            # build_bundle 内部会读几十个 key，任何一处数据异常都不应让
            # 应用起不来。回退到 light；light 都失败说明 DEFAULT_THEME 本身
            # 结构性损坏，是开发期 bug，继续抛出让问题早暴露。
            logger.exception("主题 %r 构建失败", name)
            if name == THEME_LIGHT:
                raise
            logger.warning("回退到 %s 主题", THEME_LIGHT)
            try:
                self._current = build_bundle(THEME_LIGHT, self._load(THEME_LIGHT))
            except Exception as fallback_err:
                # 用 from e 保留原始异常链：既能看到"原主题为何失败"，
                # 也能看到"light 为何也失败"。
                raise fallback_err from e

    @property
    def current(self) -> ThemeBundle:
        return self._current

    @property
    def name(self) -> str:
        return self._current.name

    def _resolve_initial(self) -> str:
        name = self._config.get("theme_name", THEME_LIGHT)
        if isinstance(name, str) and name in THEME_PRESETS:
            return name
        if name != THEME_LIGHT:
            logger.warning("配置中的主题 %r 无效，回退到 %s", name, THEME_LIGHT)
            # 顺手修正磁盘值，避免每次启动都走一遍回退分支。
            try:
                self._config.set("theme_name", THEME_LIGHT, save=True)
            except Exception:
                logger.exception("回写默认主题名失败，下次启动仍会走回退")
        return THEME_LIGHT

    @staticmethod
    def _load(name: str) -> dict:
        theme = dict(DEFAULT_THEME)
        theme.update(THEME_PRESETS.get(name) or {})
        return theme

    def set_theme(self, name: str) -> bool:
        """切换主题。返回 True 表示已切换，False 表示保持当前主题。

        构建失败、持久化失败、重入调用时都返回 False 且不修改内存状态，
        由调用方（settings_controller.apply_settings）据此把 theme_name
        回滚为当前主题名，保证磁盘与内存一致。
        """
        # 重入保护：theme_changed 的监听者可能在回调里再次调用 set_theme。
        if self._switching:
            logger.warning("主题切换进行中，忽略对 %r 的重入请求", name)
            return False
        if name not in THEME_PRESETS:
            logger.warning("未知主题 %r，忽略", name)
            return False
        if name == self._current.name:
            return True

        try:
            new_bundle = build_bundle(name, self._load(name))
        except Exception:
            logger.exception(
                "主题 %r 构建失败，保持当前主题 %r",
                name, self._current.name)
            return False

        # 先落盘再改内存：落盘失败时内存/磁盘保持一致，且不触发信号，
        # 调用方无需额外回滚。
        self._switching = True
        try:
            try:
                self._config.set("theme_name", name, save=True)
            except Exception:
                logger.exception(
                    "主题 %r 持久化失败，保持当前主题 %r",
                    name, self._current.name)
                return False

            self._current = new_bundle
            logger.info("已切换主题: %s", name)
            self.theme_changed.emit(self._current)
            return True
        finally:
            self._switching = False