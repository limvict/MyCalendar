# coding: utf-8
import os
from PyQt6.QtCore import QObject
from config import get_logger

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    winsound = None
    HAS_WINSOUND = False

logger = get_logger()

# 找不到自定义 wav 时的系统音效别名。
# 用 SND_ALIAS 播放，从注册表 HKCU\AppEvents\Schemes 查实际 wav，
# 因此不需要项目自带任何音频资源。
_SYSTEM_FALLBACK_ALIAS = "SystemAsterisk"


class SoundManager(QObject):
    """Windows 原生音效播放：无额外线程，异步不卡 UI。非 Windows 静默。

    播放策略（按优先级）：
      1. 调用方显式注册的自定义 wav（当前未用到，保留扩展位）
      2. 系统音效别名 SystemAsterisk
    两者都通过 winsound 的 SND_ASYNC 异步播放，不阻塞 UI。
    """

    def __init__(self, parent, get_resource_path, volume: float = 0.8):
        super().__init__(parent)
        self._get_resource = get_resource_path
        # winsound 走系统全局音量，不支持单独软件音量
        self._volume = volume
        self._sound_cache = {}
        self._preload_defaults()

    def _preload_defaults(self):
        """预缓存可用的自定义 wav 路径；不存在的静默跳过（走系统 fallback）。"""
        if not HAS_WINSOUND:
            logger.info("非Windows平台，音效播放已禁用")
            return

        for name in ("assets/alert.wav",):
            abs_path = os.path.abspath(self._get_resource(name))
            # 不仅要求存在，还要求非空 —— 空 wav 会让 PlaySound 静默失败
            if os.path.exists(abs_path) and os.path.getsize(abs_path) > 0:
                self._sound_cache[name] = abs_path
                logger.debug(f"音效预加载成功：{name} -> {abs_path}")
            else:
                # 降为 debug：项目设计上不再要求携带 wav，
                # 走系统音效是正常路径，不是警告。
                logger.debug(f"无自定义音效 {name}，将使用系统音效")

    def play(self, sound_name: str):
        """播放音效。自定义 wav 优先，缺失时回退系统音效。失败静默。"""
        if not HAS_WINSOUND:
            logger.debug(f"非Windows平台，忽略播放请求：{sound_name}")
            return

        sound_path = self._sound_cache.get(sound_name)

        try:
            if sound_path:
                winsound.PlaySound(
                    sound_path,
                    winsound.SND_FILENAME | winsound.SND_ASYNC)
                logger.debug(f"播放自定义音效：{sound_name}")
            else:
                winsound.PlaySound(
                    _SYSTEM_FALLBACK_ALIAS,
                    winsound.SND_ALIAS | winsound.SND_ASYNC)
                logger.debug(f"播放系统音效：{_SYSTEM_FALLBACK_ALIAS}")
        except Exception as e:
            logger.error(f"音效播放失败: {e}")