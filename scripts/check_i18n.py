# file: check_i18n.py
# coding: utf-8
"""i18n key 检查：..."""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable, Iterator, Union

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    # 直接 `python scripts/check_i18n.py` 运行时，脚本目录是 scripts/，
    # 项目根不在 sys.path；需要显式把 src 加进来才能 import desktop_calendar。
    sys.path.insert(0, str(_SRC))

from desktop_calendar.config.i18n import validate_keys  # noqa: E402
from desktop_calendar.config.translations import ZH_CN  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

__all__ = [
    "validate_keys", "validate_source_keys", "_iter_source_tr_keys", "main",
]


# ===================== 源码扫描基础设施 =====================
def _default_src_root() -> Path:
    """默认扫描路径：src/desktop_calendar。"""
    return _SRC / "desktop_calendar"


def _iter_py_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _is_tr_call(node: ast.AST) -> bool:
    """判断节点是否为 tr(...) 调用。

    只认 ast.Name（模块级 `tr`），不认 ast.Attribute（`self.tr` /
    `xxx.tr`）。PyQt 的 QObject.tr 也是 `self.tr(...)`，把它当 i18n
    key 扫进来会污染报告。
    """
    if not isinstance(node, ast.Call):
        return False
    return isinstance(node.func, ast.Name) and node.func.id == "tr"


def _iter_source_tr_keys(
    root_dir: Union[Path, str, None] = None,
    *,
    parse_errors: list[tuple[str, str]] | None = None,
) -> Iterator[tuple[str, int, str]]:
    """迭代源码中所有 tr("字面量")，yield (文件路径, 行号, key)。

    - 只产字符串字面量；f-string / 变量跳过
    - 空字符串 "" 也产出（调用方会把它报成缺失）
    - root_dir 不存在时抛 FileNotFoundError（而非静默 return）：
      后者会让 CI 在路径错误时"扫描 0 处 tr()"假绿。
    - 传入 parse_errors 时，读取/解析失败的文件会追加 (路径, 原因)，
      而不是静默跳过——否则语法坏文件里的 tr() 会漏扫。
    """
    root = Path(root_dir) if root_dir else _default_src_root()
    if not root.exists():
        raise FileNotFoundError(f"扫描根目录不存在：{root}")

    for py_file in _iter_py_files(root):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError) as e:
            if parse_errors is not None:
                parse_errors.append(
                    (str(py_file), f"{type(e).__name__}: {e}"))
            continue
        for node in ast.walk(tree):
            if not _is_tr_call(node) or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                yield str(py_file), node.lineno, first.value


# ===================== 对外校验 =====================
def validate_source_keys(
    root_dir: Union[Path, str, None] = None,
    *,
    strict: bool = False,
    allow_empty: bool = False,
) -> dict:
    """扫描源码 tr("字面量")，返回缺失 key 报告。

    返回结构：

        {
          "missing":   sorted list[str]           # 缺失 key（空列表 = 通过）
          "locations": {key: [(file, line), ...]} # 每个缺失 key 的出现位置
          "scanned":   int                        # 扫到的 tr("...") 总次数
          "empty":     bool                       # 扫描结果为 0 时为 True
          "parse_errors": [(file, reason), ...]   # 读取/解析失败的文件
        }

    :param root_dir: 扫描根目录；None 时默认 ``src/desktop_calendar``
    :param strict: True 且存在缺失/解析失败时抛异常
    :param allow_empty: True 允许 scanned == 0（单测用）；
        生产 / CI 用默认 False —— 空扫描说明根目录错或所有 .py 都
        解析失败，必须当失败处理。
    """
    known = set(ZH_CN)
    locations: dict = {}
    parse_errors: list[tuple[str, str]] = []
    scanned = 0
    for file_str, line_no, key in _iter_source_tr_keys(
            root_dir, parse_errors=parse_errors):
        scanned += 1
        if key in known:
            continue
        locations.setdefault(key, []).append((file_str, line_no))

    missing = sorted(locations.keys())
    empty = scanned == 0
    if strict and missing:
        raise KeyError(
            f"源码 tr() 缺失 {len(missing)} 个 key：{missing}")
    if strict and parse_errors:
        raise RuntimeError(
            f"源码解析失败 {len(parse_errors)} 个文件：{parse_errors[:3]}")
    if strict and empty and not allow_empty:
        raise RuntimeError("源码扫描到 0 处 tr() 调用，疑似路径错误")
    return {
        "missing": missing,
        "locations": locations,
        "scanned": scanned,
        "empty": empty,
        "parse_errors": parse_errors,
    }


# ===================== CLI =====================
def main() -> int:
    exit_code = 0

    report = validate_keys(strict=False)
    if report:
        exit_code = 1
        for code, info in report.items():
            print(f"[lang {code}]")
            for k in ("missing", "extra", "placeholder_mismatch"):
                if info[k]:
                    print(f"  {k}: {info[k]}")

    try:
        src_rep = validate_source_keys(strict=False)
    except FileNotFoundError as e:
        print(f"[source] {e}", file=sys.stderr)
        return 1

    if src_rep["parse_errors"]:
        exit_code = 1
        print(
            f"[source] {len(src_rep['parse_errors'])} 个文件读取/解析失败"
            f"（其中的 tr() 未参与校验）：",
            file=sys.stderr,
        )
        for file_str, reason in src_rep["parse_errors"]:
            print(f"  {file_str}: {reason}", file=sys.stderr)

    if src_rep["empty"]:
        exit_code = 1
        print(
            "[source] 扫描到 0 处 tr() 调用——CI 环境路径错误或"
            "所有 .py 均解析失败，不能视为通过",
            file=sys.stderr,
        )
    if src_rep["missing"]:
        exit_code = 1
        print(f"[source] 缺失 {len(src_rep['missing'])} 个 tr() key：")
        for key in src_rep["missing"]:
            refs = src_rep["locations"][key]
            suffix = " ..." if len(refs) > 3 else ""
            print(f"  {key!r} @ {refs[:3]}{suffix}")

    if exit_code == 0:
        print(f"OK（扫描 {src_rep['scanned']} 处 tr()）")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())