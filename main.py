# coding: utf-8
"""
程序入口（薄引导层）。

只做两件事：
  1. 把 src/ 加入 sys.path（未 pip install -e . 时兜底）
  2. 调 desktop_calendar.__main__.main()

真正的启动逻辑在 src/desktop_calendar/__main__.py。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> Path:
    """把本文件同级 src/ 前置到 sys.path（优先于已安装版本）。"""
    src = Path(__file__).resolve().parent / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return src


def main() -> int:
    src = _ensure_src_on_path()
    try:
        from desktop_calendar.__main__ import main as app_main
    except ImportError as e:
        # 入口脚本失败时给出可操作的提示，而不是裸 traceback。
        # 常见原因：src/desktop_calendar 缺失、未 pip install -e .、
        # 或包内 __main__ 的依赖缺失。
        print(
            f"无法导入 desktop_calendar：{e}\n"
            f"  预期源码目录: {src}\n"
            "  请确认 src/desktop_calendar 存在，或已执行 pip install -e .",
            file=sys.stderr,
        )
        return 1
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())