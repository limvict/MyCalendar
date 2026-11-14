# coding: utf-8
"""
程序入口（薄引导层）。

只做两件事：
  1. 把 src/ 加入 sys.path（未 pip install -e . 时兜底）
  2. 调 desktop_calendar.__main__.main()

真正的启动逻辑在 src/desktop_calendar/__main__.py。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_src_on_path() -> Path:
    """把本文件同级 src/ 前置到 sys.path（优先于已安装版本）。"""
    src = Path(__file__).resolve().parent / "src"
    if src.is_dir():
        # 用 realpath 比较，避免尾斜杠 / 符号链接导致重复插入。
        real = os.path.realpath(str(src))
        if not any(os.path.realpath(p) == real for p in sys.path if p):
            sys.path.insert(0, str(src))
    return src


def main() -> int:
    src = _ensure_src_on_path()
    try:
        # 注意：app_main() 的调用也放在 try 内。__main__.py 把
        # config / ui 的导入延迟到双开检查之后（函数体内），
        # 这些导入的 ImportError 发生在调用期间而非 import 期间，
        # 若不放进来就会被漏掉，变成裸 traceback。
        from desktop_calendar.__main__ import main as app_main
        return app_main()
    except ImportError as e:
        # 按缺失模块区分提示：缺 desktop_calendar 包本身 vs 缺第三方
        # 依赖（如 PyQt6），两者处置方式不同。
        missing = getattr(e, "name", None) or ""
        lines = [f"无法导入 desktop_calendar：{e}"]
        if missing.split(".")[0] == "desktop_calendar":
            lines.append(f"  预期源码目录: {src}")
            lines.append(
                "  请确认 src/desktop_calendar 存在（含 __main__.py），"
                "或已执行 pip install -e .")
        else:
            lines.append(f"  缺失的依赖: {missing or '未知'}")
            lines.append("  请先安装项目依赖（如 pip install -e .）")
        print("\n".join(lines), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
