# coding: utf-8
"""ThemeManager：当前主题 Bundle + 切换/持久化。"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

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
            # 持久化 light：否则磁盘上仍是坏掉的主题名，下次启动会重复
            # 走"构建失败 → 回退"路径，日志被刷屏且用户无感知。写盘失败
            # 不应让应用起不来，仅记录。
            try:
                self._config.set("theme_name", THEME_LIGHT, save=True)
            except Exception:
                logger.exception(
                    "回退到 %s 后回写主题名失败，下次启动仍会重试", THEME_LIGHT)

    @property
    def current(self) -> ThemeBundle:
        return self._current

    @property
    def name(self) -> str:
        return self._current.name

    @property
    def switching(self) -> bool:
        """只读：是否正处于一次切换的信号分发期。供调试/断言用。"""
        return self._switching

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

        持久化走 set(save=False) + flush(raise_on_error=True)：同步写盘，
        失败时回滚内存中的 theme_name 并返回 False。与原实现
        set(save=True) 的区别：后者只是启动 debounce Timer，set_theme
        返回 True 时磁盘可能尚未写入（磁盘满 / 权限问题延迟暴露），
        与 docstring 声称的「先落盘再改内存」契约不符。
        """
        if self._switching:
            logger.warning("主题切换进行中，忽略对 %r 的重入请求", name)
            return False
        if name not in THEME_PRESETS:
            logger.warning("未知主题 %r，忽略", name)
            return False
        if name == self._current.name:
            # 内存已是目标主题，顺手修正磁盘（尽力而为，失败不影响返回值）
            if self._config.get("theme_name", None) != name:
                try:
                    self._config.set("theme_name", name, save=True)
                except Exception:
                    logger.exception(
                        "内存已是主题 %r，但回写磁盘失败，下次启动可能不一致",
                        name)
            return True

        try:
            new_bundle = build_bundle(name, self._load(name))
        except Exception:
            logger.exception(
                "主题 %r 构建失败，保持当前主题 %r",
                name, self._current.name)
            return False

        old_name = self._current.name
        self._switching = True
        try:
            self._config.set("theme_name", name, save=False)
            try:
                self._config.flush(raise_on_error=True)
            except Exception:
                # flush 失败：atomic_write_json 在 os.replace 前抛，磁盘
                # 未变。回滚内存 theme_name 即与磁盘一致；save=False
                # 避免在失败路径上再次触发 IO。
                try:
                    self._config.set("theme_name", old_name, save=False)
                except Exception:
                    logger.exception(
                        "回滚 theme_name 到 %r 失败，内存可能与磁盘不一致",
                        old_name)
                logger.exception(
                    "主题 %r 持久化失败，保持当前主题 %r",
                    name, self._current.name)
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

        set_theme 的 _switching 保护会拒绝信号分发期内的重入。若监听者
        确实需要"刷新后联动切到另一主题"，走本方法把调用推迟到当前
        emit 栈退出之后，语义上等价于 QTimer.singleShot(0, ...)。

        边界：
        - 本方法不返回值，也不保证切换成功（未知主题 / 构建失败时
          set_theme 内部静默拒绝并记日志），调用方若需结果可监听
          theme_changed 或轮询 current.name。
        - 若 manager 在定时器触发前销毁（应用退出期），lambda 内对
          self 的调用会抛 RuntimeError；这里捕获并降级为 debug 日志，
          不污染退出流程。
        """
        def _fire() -> None:
            try:
                self.set_theme(name)
            except RuntimeError:
                # C++ 对象已销毁：manager 随应用退出，忽略即可
                logger.debug(
                    "set_theme_async: manager 已销毁，忽略 %r", name)
        QTimer.singleShot(delay_ms, _fire)