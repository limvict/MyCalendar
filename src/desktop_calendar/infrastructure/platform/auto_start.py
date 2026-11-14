# coding: utf-8
"""Windows 开机自启（注册表 Run 键）。非 Windows 抛 OSError。

键名说明：
  - 当前键 ``DesktopCalendarV3`` —— 与 ``build/installer.iss``
    的 ``ValueName`` 保持一致（安装器勾选"开机自启动"时写的就是
    这个键）。早期版本误用 ``DesktopLunarCalendarV3``，导致"安装
    器写的键程序读不到、程序写的键卸载器清不掉"。
  - 旧键 ``DesktopLunarCalendarV3`` —— 历史应用名 Desktop Lunar
    Calendar 时期写的键。``_migrate_legacy_key()`` 会在首次读写
    时把它迁移到当前键并删除，避免存量用户丢自启。

迁移策略：
  - 若旧键存在、新键不存在：用**当前 exe 路径**（而非复制旧值）
    写新键。旧值可能指向已卸载的旧版本 exe，直接复制会让自启
    指向不存在的文件；而写当前路径天然正确。
  - 若新旧键同时存在：只删旧键，不覆盖新键（用户可能已在程序
    设置里主动改过）。
  - 迁移失败（权限等）静默：正式路径 ``is_enabled`` / ``set_enabled``
    仍能工作，只是多一次 legacy 读取兜底。
"""
import os
import sys

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    winreg = None
    HAS_WINREG = False

from desktop_calendar.utils.logging_setup import get_logger

logger = get_logger()

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_KEY = "DesktopCalendarV3"
_LEGACY_REG_KEY = "DesktopLunarCalendarV3"


class AutoStartError(OSError):
    """注册表操作失败。reason 供上层映射 i18n key。"""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        # "unsupported" | "permission" | "path_missing" | "unknown"


def is_supported() -> bool:
    return sys.platform == "win32" and HAS_WINREG


# ==================== 内部辅助 ====================
def _read_value(key, name: str):
    """读取注册表值；键不存在返回 None。异常由调用方兜底。"""
    try:
        val, _ = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    return val


def _delete_value_silent(key, name: str) -> None:
    """删除值；不存在时静默。其他异常（权限）继续抛出由外层处理。"""
    try:
        winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def _build_cmd() -> str:
    if getattr(sys, "_MEIPASS", None):
        return f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0])
    if script.endswith(".py"):
        return f'"{sys.executable}" "{script}"'
    return f'"{sys.executable}"'


def _migrate_legacy_key() -> None:
    """把旧键迁移到当前键。幂等；失败静默。

    只在 HKCU\\...\\Run 上操作，不涉及其他位置。调用时机：
    is_enabled / set_enabled 内部，用户首次读写自启状态时触发。

    注意事项：
      - 需要 KEY_SET_VALUE 权限；权限不足时抛 PermissionError，
        被本函数内部捕获后仅记 debug。is_enabled 会退化为只读
        legacy 兜底。
      - 写入新键时使用 _build_cmd() 而非旧键值 —— 见模块 docstring。
    """
    if not is_supported():
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _REG_PATH,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            # 旧键不存在 → 无事可做
            if _read_value(key, _LEGACY_REG_KEY) is None:
                return
            # 旧键存在：新键缺失时补写（用当前 exe 路径，不复制旧值）
            if _read_value(key, _REG_KEY) is None:
                winreg.SetValueEx(
                    key, _REG_KEY, 0, winreg.REG_SZ, _build_cmd())
                logger.info(
                    "自启注册表键已迁移：%s -> %s",
                    _LEGACY_REG_KEY, _REG_KEY)
            # 无论是否补写，都清掉旧键
            _delete_value_silent(key, _LEGACY_REG_KEY)
    except Exception:
        logger.debug("迁移旧自启注册表键失败", exc_info=True)


# ==================== 对外 API ====================
def is_enabled() -> bool:
    """判断是否启用自启。

    先触发一次旧键迁移；随后读新键。若新键仍不存在（迁移因权限
    等原因未成功），退化为直接读旧键 —— 保证存量用户的"已开启"
    状态不会因为一次权限失败而显示错。
    """
    if not is_supported():
        return False

    _migrate_legacy_key()

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            val = _read_value(key, _REG_KEY)
            if val is None:
                # 迁移失败时的兜底：直接读旧键判定真实状态。
                # 用户随后手动 toggle 会在 set_enabled 中一并清理旧键。
                val = _read_value(key, _LEGACY_REG_KEY)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_enabled(enable: bool) -> None:
    """开启/关闭自启。失败抛 AutoStartError。

    - enable=True  ：写新键，同时清理旧键（避免 legacy 残留干扰
      后续 is_enabled 的兜底分支）。
    - enable=False ：删新键与旧键。必须两键都删，否则
      is_enabled 的 legacy 兜底会让"用户明确关闭"看起来仍是开启。

    用 CreateKeyEx 而非 OpenKey：Run 键若被用户/恶意软件删除，
    OpenKey 抛 FileNotFoundError，会被误判为 "path_missing"
    （程序路径不存在），实际是注册表键缺失。CreateKeyEx 自动创建，
    语义正确。
    """
    if not is_supported():
        raise AutoStartError("unsupported")
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            _REG_PATH,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        ) as key:
            if enable:
                winreg.SetValueEx(
                    key, _REG_KEY, 0, winreg.REG_SZ, _build_cmd())
                _delete_value_silent(key, _LEGACY_REG_KEY)
            else:
                _delete_value_silent(key, _REG_KEY)
                _delete_value_silent(key, _LEGACY_REG_KEY)
    except PermissionError as e:
        raise AutoStartError("permission", str(e)) from e
    except FileNotFoundError as e:
        # CreateKeyEx 理论上不会 FileNotFoundError（HKCU 一定存在），
        # 保留作为兜底。用 "unknown" 而非 "path_missing"，避免误导——
        # 此时不是程序路径问题，是注册表访问问题。
        raise AutoStartError("unknown", str(e)) from e
    except Exception as e:
        raise AutoStartError("unknown", str(e)) from e