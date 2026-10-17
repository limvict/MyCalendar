# coding: utf-8
"""
程序入口（薄引导层）。

只做两件事：
  1. 把 src/ 加入 sys.path（未 pip install -e . 时兜底）
  2. 调 desktop_calendar.app.entry.main()

真正的启动逻辑在 src/desktop_calendar/app/entry.py。
"""
import sys
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from desktop_calendar.app.entry import main

if __name__ == "__main__":
    raise SystemExit(main())