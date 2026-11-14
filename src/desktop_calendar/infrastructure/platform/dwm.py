# coding: utf-8
"""DWM（Desktop Window Manager）窗口效果修复。

- 消除无边框窗口的黑边：DwmExtendFrameIntoClientArea 全窗口边距。
- 深色主题标题栏：DwmSetWindowAttribute DWMWA_USE_IMMERSIVE_DARK_MODE。

所有调用失败静默（debug 日志），不影响主功能。
"""
import ctypes
import sys

from desktop_calendar.utils.logging_setup import get_logger

logger = get_logger()


class _MARGINS(ctypes.Structure):
    """ctypes 结构体放模块级：避免每次调用重新构造类。"""
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int)]


# DWMWA_USE_IMMERSIVE_DARK_MODE 在 Win10 1809 (build 17763) 之前是 19，
# 之后是 20。用 20 在旧系统上 DwmSetWindowAttribute 返回 E_INVALIDARG，
# 被下方 try/except 吞掉，仅深色标题栏不生效（非关键功能）。
# 不支持 19 是有意的：本程序最低支持 Win10，1809 之前的版本极罕见，
# 为兼容它们增加运行时探测代码收益不抵复杂度。
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20


def apply_dwm_fix(window, dark_mode=False) -> None:
    """对窗口应用 DWM 效果。非 Windows / 调用失败静默。

    必须在窗口句柄已创建后调用（setWindowFlags 之后、首次 paint
    之前）。setWindowFlags 会重建原生句柄，句柄变化后需重新调用。
    """
    if sys.platform != "win32":
        return
    try:
        dwmapi = ctypes.windll.dwmapi

        # 显式声明 argtypes：默认按 C int 转换会把 64 位句柄高 32 位
        # 截断，DWM 调用作用于错误句柄。c_void_p 保证 32/64 位正确。
        dwmapi.DwmExtendFrameIntoClientArea.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_MARGINS)]
        dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
        dwmapi.DwmSetWindowAttribute.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

        hwnd = int(window.winId())

        # 1. 消除黑边：margins 全 -1 表示扩展到整个客户区
        margins = _MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

        # 2. 深色标题栏（Win10 1809+ 有效，旧系统静默失败）
        if dark_mode:
            value = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
    except Exception:
        # 非关键功能，失败记 debug。频繁 warning 会刷屏（旧系统每次
        # 切主题都调用）。
        logger.debug("DWM 修复失败 dark_mode=%s", dark_mode, exc_info=True)