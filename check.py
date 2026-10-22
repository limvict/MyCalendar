import pathlib, sys
root = pathlib.Path(r"E:\Demo\src")
sys.path.insert(0, str(root))

# 1) 逐层尝试 import
for name in [
    "desktop_calendar",
    "desktop_calendar.infrastructure",
    "desktop_calendar.infrastructure.network",
    "desktop_calendar.infrastructure.network.updater",
]:
    try:
        __import__(name)
        print(f"OK    {name}")
    except Exception as e:
        print(f"FAIL  {name}  ->  {type(e).__name__}: {e}")
        break

# 2) 直接看磁盘
net = root / "desktop_calendar" / "infrastructure" / "network"
print("\n---", net, "exists:", net.exists())
if net.exists():
    for p in net.iterdir():
        print(f"  {'DIR ' if p.is_dir() else 'FILE'}  {p.name!r}")
    upd = net / "updater.py"
    print(f"\nupdater.py 存在? {upd.exists()}")
    if upd.exists():
        print(f"  大小: {upd.stat().st_size} 字节")
        print(f"  内容前 5 行:")
        for line in upd.read_text(encoding="utf-8", errors="replace").splitlines()[:5]:
            print("   ", line)