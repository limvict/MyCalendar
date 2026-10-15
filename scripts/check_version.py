# coding: utf-8
"""
CI 校验：updater.CURRENT_VERSION 与 installer.iss 的 AppVersion 必须一致。
用法：python scripts/check_version.py
"""
import re
import sys
import pathlib

def _read(path: str) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8")

def main() -> int:
    updater_src = _read("updater.py")
    iss_src = _read("installer.iss")

    m1 = re.search(r'CURRENT_VERSION\s*=\s*"([^"]+)"', updater_src)
    m2 = re.search(r'AppVersion\s*=\s*"([^"]+)"', iss_src)
    if not m1 or not m2:
        print("ERROR: 无法从源码中解析版本号")
        return 1

    py, iss = m1.group(1), m2.group(1)
    if py != iss:
        print(f"ERROR: 版本不一致 updater.py={py} installer.iss={iss}")
        return 1

    print(f"OK: 版本一致 {py}")
    return 0

if __name__ == "__main__":
    sys.exit(main())