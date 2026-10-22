# coding: utf-8
"""i18n key 检查：
  - validate_keys        — 语言包之间 key / 占位符一致性（在 i18n 里）
  - validate_source_keys — AST 扫描源码 tr("字面量") 是否都在 ZH_CN
  - _iter_source_tr_keys — 底层的源码 tr() 迭代器

CLI 入口见 main()。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Iterator, Union

from desktop_calendar.config.i18n import validate_keys  # re-export
from desktop_calendar.config.translations import ZH_CN

__all__ = [
    "validate_keys", "validate_source_keys", "_iter_source_tr_keys", "main",
]


# ===================== 源码扫描基础设施 =====================
def _default_src_root() -> Path:
    """默认扫描路径：src/desktop_calendar。"""
    # scripts/check_i18n.py → 上两级 = 项目根
    return Path(__file__).resolve().parent.parent / "src" / "desktop_calendar"


def _iter_py_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _is_tr_call(node: ast.AST) -> bool:
    """判断节点是否为 tr(...) 或 xxx.tr(...) 调用。"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "tr":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "tr":
        return True
    return False


def _iter_source_tr_keys(
    root_dir: Union[Path, str, None] = None,
) -> Iterator[tuple[str, int, str]]:
    """迭代源码中所有 tr("字面量")，yield (文件路径, 行号, key)。

    - 只产字符串字面量；f-string / 变量跳过
    - 空字符串 "" 也产出（调用方会把它报成缺失）
    """
    root = Path(root_dir) if root_dir else _default_src_root()
    if not root.exists():
        return

    for py_file in _iter_py_files(root):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError):
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
) -> dict:
    """扫描源码 tr("字面量")，返回缺失 key 报告。

    返回结构与 validate_keys 呼应：

        {
          "missing":   sorted list[str]           # 缺失 key（空列表 = 通过）
          "locations": {key: [(file, line), ...]} # 每个缺失 key 的出现位置
          "scanned":   int                        # 扫到的 tr("...") 总次数
        }

    :param root_dir: 扫描根目录；None 时默认 ``src/desktop_calendar``
    :param strict: True 且存在缺失时抛 KeyError
    """
    known = set(ZH_CN)
    locations: dict = {}
    scanned = 0
    for file_str, line_no, key in _iter_source_tr_keys(root_dir):
        scanned += 1
        if key in known:
            continue
        locations.setdefault(key, []).append((file_str, line_no))

    missing = sorted(locations.keys())
    if strict and missing:
        raise KeyError(
            f"源码 tr() 缺失 {len(missing)} 个 key：{missing}")
    return {
        "missing": missing,
        "locations": locations,
        "scanned": scanned,
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

    src_rep = validate_source_keys(strict=False)
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