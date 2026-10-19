# coding: utf-8
"""Windows 开机自启（注册表 Run 键）。非 Windows 抛 OSError。"""
import os
import sys

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    winreg = None
    HAS_WINREG = False

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_KEY = "DesktopLunarCalendarV3"


class AutoStartError(OSError):
    """注册表操作失败。reason 供上层映射 i18n key。"""
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason          # "unsupported" | "permission" | "path_missing" | "unknown"


def is_supported() -> bool:
    return sys.platform == "win32" and HAS_WINREG


def is_enabled() -> bool:
    if not is_supported():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            val, _ = winreg.QueryValueEx(key, _REG_KEY)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _build_cmd() -> str:
    if getattr(sys, "_MEIPASS", None):
        return f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0])
    if script.endswith(".py"):
        return f'"{sys.executable}" "{script}"'
    return f'"{sys.executable}"'


def set_enabled(enable: bool) -> None:
    """开启/关闭自启。失败抛 AutoStartError。"""
    if not is_supported():
        raise AutoStartError("unsupported")
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _REG_PATH, 0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, _REG_KEY, 0, winreg.REG_SZ, _build_cmd())
            else:
                try:
                    winreg.DeleteValue(key, _REG_KEY)
                except FileNotFoundError:
                    pass
    except PermissionError as e:
        raise AutoStartError("permission", str(e)) from e
    except FileNotFoundError as e:
        raise AutoStartError("path_missing", str(e)) from e
    except Exception as e:
        raise AutoStartError("unknown", str(e)) from e