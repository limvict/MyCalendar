# coding: utf-8
"""ThemeManager：当前主题 Bundle + 切换/持久化。"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from desktop_calendar.config.constants import (
    DEFAULT_THEME,
    THEME_DARK,
    THEME_LIGHT,
    THEME_PRESETS,
)
from desktop_calendar.config.manager import ConfigManager, get_logger

from .bundle import ThemeBundle, build_bundle, normalize_ui_scale

logger = get_logger()


class ThemeManager(QObject):
    theme_changed = pyqtSignal(object)

    def __init__(self, config: ConfigManager, *, ui_scale: float = 1.0):
        super().__init__()
        self._config = config
        self._ui_scale = normalize_ui_scale(ui_scale)
        self._switching = False
        self._auto_theme_enabled = bool(self._config.get("theme_auto_enabled", False))
        self._auto_theme_timer = QTimer(self)
        self._auto_theme_timer.setInterval(60_000)
        self._auto_theme_timer.timeout.connect(self._sync_auto_theme)
        name = self._resolve_initial()
        try:
            self._current: ThemeBundle = self._build_bundle(name)
        except Exception as e:
            # 任何数据异常不应让应用起不来；light 也失败则是 DEFAULT_THEME 损坏，直接抛
            logger.exception("主题 %r 构建失败", name)
            if name == THEME_LIGHT:
                raise
            logger.warning("回退到 %s 主题", THEME_LIGHT)
            try:
                self._current = self._build_bundle(THEME_LIGHT)
            except Exception as fallback_err:
                raise fallback_err from e
            # 回写磁盘避免下次启动重复走回退分支
            try:
                self._config.set("theme_name", THEME_LIGHT, save=True)
            except Exception:
                logger.exception("回退到 %s 后回写主题名失败，下次启动仍会重试", THEME_LIGHT)
        if self._auto_theme_enabled:
            self._auto_theme_timer.start()
            self._sync_auto_theme()

    @property
    def current(self) -> ThemeBundle:
        return self._current

    @property
    def name(self) -> str:
        return self._current.name

    @property
    def switching(self) -> bool:
        return self._switching

    @staticmethod
    def _automatic_theme_for_hour(hour: int) -> str:
        return THEME_LIGHT if 7 <= hour < 19 else THEME_DARK

    def set_auto_theme_enabled(self, enabled: bool) -> bool:
        """Enable local-time light/dark switching without changing manual mode."""
        self._auto_theme_enabled = bool(enabled)
        if not self._auto_theme_enabled:
            self._auto_theme_timer.stop()
            return True
        self._auto_theme_timer.start()
        return self._sync_auto_theme()

    def _sync_auto_theme(self) -> bool:
        if not self._auto_theme_enabled:
            return True
        name = self._automatic_theme_for_hour(datetime.now().hour)
        if name == self._current.name:
            return True
        return self.set_theme(name)

    def set_ui_scale(self, scale: float) -> bool:
        """更新屏幕适配比例，不修改主题配置。"""
        scale = normalize_ui_scale(scale)
        if scale == self._ui_scale:
            return False
        try:
            new_bundle = self._build_bundle(self._current.name, scale=scale)
        except Exception:
            logger.exception("构建缩放主题失败 scale=%s", scale)
            return False
        self._ui_scale = scale
        self._current = new_bundle
        try:
            self.theme_changed.emit(self._current)
        except Exception:
            logger.exception("ui_scale_changed 监听者抛出异常")
        return True

    def preview_theme(self, name: str) -> bool:
        """Apply a theme temporarily without changing the saved configuration."""
        if name not in THEME_PRESETS:
            logger.warning("未知预览主题 %r，忽略", name)
            return False
        if name == self._current.name:
            return True
        try:
            bundle = self._build_bundle(name)
        except Exception:
            logger.exception("构建预览主题 %r 失败", name)
            return False
        self._current = bundle
        try:
            self.theme_changed.emit(bundle)
        except Exception:
            logger.exception("theme_changed 预览监听者抛出异常")
        return True

    def _build_bundle(self, name: str, *, scale: float | None = None) -> ThemeBundle:
        return build_bundle(
            name, self._load(name), scale=self._ui_scale if scale is None else scale
        )

    def _resolve_initial(self) -> str:
        name = self._config.get("theme_name", THEME_LIGHT)
        if isinstance(name, str) and name in THEME_PRESETS:
            return name
        if name != THEME_LIGHT:
            logger.warning("配置中的主题 %r 无效，回退到 %s", name, THEME_LIGHT)
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

        持久化走 set(save=False) + flush(raise_on_error=True)：同步写盘，
        失败时回滚内存 theme_name 并返回 False，保证返回 True 时磁盘已写入。
        """
        if self._switching:
            logger.warning("主题切换进行中，忽略对 %r 的重入请求", name)
            return False
        if name not in THEME_PRESETS:
            logger.warning("未知主题 %r，忽略", name)
            return False
        if name == self._current.name:
            if self._config.get("theme_name", None) != name:
                try:
                    self._config.set("theme_name", name, save=True)
                except Exception:
                    logger.exception("内存已是主题 %r，但回写磁盘失败，下次启动可能不一致", name)
            return True

        try:
            new_bundle = self._build_bundle(name)
        except Exception:
            logger.exception("主题 %r 构建失败，保持当前主题 %r", name, self._current.name)
            return False

        old_name = self._current.name
        self._switching = True
        try:
            self._config.set("theme_name", name, save=False)
            try:
                self._config.flush(raise_on_error=True)
            except Exception:
                # flush 失败：atomic_write_json 在 os.replace 前抛，磁盘未变。
                try:
                    self._config.set("theme_name", old_name, save=False)
                except Exception:
                    logger.exception("回滚 theme_name 到 %r 失败，内存可能与磁盘不一致", old_name)
                logger.exception("主题 %r 持久化失败，保持当前主题 %r", name, self._current.name)
                return False

            self._current = new_bundle
            logger.info("已切换主题: %s", name)
            try:
                self.theme_changed.emit(self._current)
            except Exception:
                logger.exception("theme_changed 监听者抛出异常")
            return True
        finally:
            self._switching = False

    def set_theme_async(self, name: str, *, delay_ms: int = 0) -> None:
        """异步切换：供 theme_changed 监听者在回调内安全触发下一次切换。

        set_theme 的 _switching 保护拒绝信号分发期内重入；本方法把调用
        推迟到当前 emit 栈退出之后。不返回值，失败时静默记日志。
        """

        def _fire() -> None:
            try:
                self.set_theme(name)
            except RuntimeError:
                logger.debug("set_theme_async: manager 已销毁，忽略 %r", name)

        QTimer.singleShot(delay_ms, _fire)
