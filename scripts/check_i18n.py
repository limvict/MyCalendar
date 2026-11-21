# file: check_i18n.py
# coding: utf-8
"""i18n key 检查：源码 tr() 字面量 + *I18N* 字典值 + tr().format() 参数。

单语言项目：只保证源码引用的 key 都在 ZH_CN 中定义。
"""

from __future__ import annotations

import ast
import re
import string
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from desktop_calendar.config.translations import ZH_CN  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

__all__ = [
    "validate_source_keys",
    "validate_dict_i18n_keys",
    "validate_tr_format_keys",
    "_iter_source_tr_keys",
    "_iter_dict_i18n_keys",
    "_iter_tr_format_calls",
    "_placeholders",
    "main",
]

# 模块级 i18n 字典命名约定：变量名含 I18N（如 _REASON_I18N_KEYS）。
_I18N_DICT_NAME_RE = re.compile(r"(^|_)I18N(_|$)")

# 回退正则：仅在 string.Formatter 解析失败（非法模板）时使用。
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

# string.Formatter 正确识别 {{ }} 转义、{name!r}、{count:,} 等语法，
# 避免旧正则把 {{name}} 误判为占位符、把 {count:,} 漏掉。
_FORMATTER = string.Formatter()

# 同一批文件被三个扫描器各解析一次太浪费，缓存 (mtime_ns, AST)。
# 缓存 mtime 使文件修改后自动失效，避免长期进程返回旧 AST。
_AST_CACHE: dict[str, tuple[int, ast.AST]] = {}


def _placeholders(text: str) -> set:
    """返回文本中所有 format 占位符的根字段名集合。

    用 string.Formatter 正确解析 {{ }} / !r / :format_spec；非法模板
    回退到宽松正则，避免检查器因模板错误崩溃。
    """
    names: set = set()
    try:
        for _, field_name, _, _ in _FORMATTER.parse(text or ""):
            if not field_name:
                continue
            # {a.b} / {a[0]} 的根字段是 a；{[0]} 是位置参数键，跳过。
            root = re.split(r"[.\[]", field_name, maxsplit=1)[0]
            if root:
                names.add(root)
    except ValueError:
        return set(_PLACEHOLDER_RE.findall(text or ""))
    return names


def _default_src_root() -> Path:
    return _SRC / "desktop_calendar"


def _iter_py_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _iter_ast_trees(
    root_dir: Path | str | None,
    parse_errors: list[tuple[str, str]] | None = None,
) -> Iterator[tuple[str, ast.AST]]:
    """遍历 root 下所有 .py，yield (路径, AST)。

    解析失败的文件追加到 parse_errors 后跳过。root 不存在时抛
    FileNotFoundError，避免 CI 路径错误时"扫描 0 处"假绿。
    """
    root = Path(root_dir) if root_dir else _default_src_root()
    if not root.exists():
        raise FileNotFoundError(f"扫描根目录不存在：{root}")
    for py_file in _iter_py_files(root):
        key = str(py_file)
        try:
            mtime = py_file.stat().st_mtime_ns
        except OSError:
            mtime = 0
        cached = _AST_CACHE.get(key)
        if cached is not None and cached[0] == mtime:
            yield key, cached[1]
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=key)
        except (OSError, SyntaxError) as e:
            _AST_CACHE.pop(key, None)
            if parse_errors is not None:
                parse_errors.append((key, f"{type(e).__name__}: {e}"))
            continue
        _AST_CACHE[key] = (mtime, tree)
        yield key, tree


def _is_tr_call(node: ast.AST) -> bool:
    """只认模块级 tr(...)，不认 self.tr / xxx.tr（PyQt QObject.tr）。"""
    if not isinstance(node, ast.Call):
        return False
    return isinstance(node.func, ast.Name) and node.func.id == "tr"


def _iter_source_tr_keys(
    root_dir: Path | str | None = None,
    *,
    parse_errors: list[tuple[str, str]] | None = None,
) -> Iterator[tuple[str, int, str]]:
    """迭代源码中 tr("字面量")，yield (文件, 行号, key)。"""
    for file_str, tree in _iter_ast_trees(root_dir, parse_errors):
        for node in ast.walk(tree):
            if not _is_tr_call(node) or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                yield file_str, node.lineno, first.value


def _i18n_dict_name(node: ast.AST) -> str | None:
    """若 node 是 NAME = {dict} 或 NAME: T = {dict} 且 NAME 含 I18N，返回 NAME。"""
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            return None
        target = node.targets[0]
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        target = node.target
        value = node.value
        if value is None:
            return None
    else:
        return None
    if not isinstance(target, ast.Name):
        return None
    if not _I18N_DICT_NAME_RE.search(target.id):
        return None
    if not isinstance(value, ast.Dict):
        return None
    return target.id


def _iter_dict_i18n_keys(
    root_dir: Path | str | None = None,
    *,
    parse_errors: list[tuple[str, str]] | None = None,
) -> Iterator[tuple[str, int, str, str]]:
    """迭代 *I18N* = {k: "v"} 字典的字符串值，yield (文件, 行号, 变量名, key)。"""
    for file_str, tree in _iter_ast_trees(root_dir, parse_errors):
        for node in ast.walk(tree):
            name = _i18n_dict_name(node)
            if name is None:
                continue
            for v in node.value.values:
                if not (isinstance(v, ast.Constant) and isinstance(v.value, str)):
                    continue
                if not v.value:
                    continue
                yield file_str, v.lineno, name, v.value


def _build_parent_map(tree: ast.AST) -> dict:
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _iter_tr_format_calls(
    root_dir: Path | str | None = None,
    *,
    parse_errors: list[tuple[str, str]] | None = None,
) -> Iterator[tuple[str, int, str, set, bool]]:
    """迭代 tr("k").format(**kw) / tr("k", **kw)。

    yield (文件, 行号, key, 明确 kwargs 名集合, has_star)。
    has_star=True 表示调用含 **kwargs 展开，未覆盖占位符降级为 uncertain。
    """
    for file_str, tree in _iter_ast_trees(root_dir, parse_errors):
        parents = _build_parent_map(tree)

        for node in ast.walk(tree):
            if not _is_tr_call(node) or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            key = first.value

            parent = parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.attr == "format":
                grand = parents.get(parent)
                if isinstance(grand, ast.Call):
                    explicit = {kw.arg for kw in grand.keywords if kw.arg}
                    has_star = any(kw.arg is None for kw in grand.keywords)
                    yield (file_str, grand.lineno, key, explicit, has_star)
                    continue

            if node.keywords:
                explicit = {kw.arg for kw in node.keywords if kw.arg}
                has_star = any(kw.arg is None for kw in node.keywords)
                yield (file_str, node.lineno, key, explicit, has_star)


def validate_tr_format_keys(
    root_dir: Path | str | None = None,
    *,
    strict: bool = False,
) -> dict:
    """校验 tr().format() / tr(..., **kw) 是否覆盖占位符。

    返回 {missing, uncertain, locations, scanned, parse_errors}。
    只校验 key 在 ZH_CN 中的调用；含 ** 展开的未覆盖占位符记 uncertain。
    strict=True 时 parse_errors / missing 抛异常，uncertain 不抛。
    """
    known = set(ZH_CN)
    missing: dict = {}
    uncertain: dict = {}
    locations: dict = {}
    parse_errors: list[tuple[str, str]] = []
    scanned = 0

    for file_str, line_no, key, kwargs, has_star in _iter_tr_format_calls(
        root_dir, parse_errors=parse_errors
    ):
        scanned += 1
        if key not in known:
            continue
        required = _placeholders(ZH_CN[key])
        gap = required - kwargs
        if not gap:
            continue
        if has_star:
            uncertain.setdefault(key, set()).update(gap)
        else:
            missing.setdefault(key, set()).update(gap)
        locations.setdefault(key, []).append((file_str, line_no))

    if strict and parse_errors:
        raise RuntimeError(
            f"源码解析失败 {len(parse_errors)} 个文件"
            f"（format kwargs 校验不完整）：{parse_errors[:3]}"
        )
    if strict and missing:
        raise KeyError(f"tr().format() 缺少占位符参数 {len(missing)} 处：{missing}")

    return {
        "missing": {k: sorted(v) for k, v in missing.items()},
        "uncertain": {k: sorted(v) for k, v in uncertain.items()},
        "locations": locations,
        "scanned": scanned,
        "parse_errors": parse_errors,
    }


def validate_source_keys(
    root_dir: Path | str | None = None,
    *,
    strict: bool = False,
    allow_empty: bool = False,
) -> dict:
    """扫描源码 tr("字面量")，返回 {missing, locations, scanned, empty, parse_errors}。

    allow_empty=True 允许 scanned == 0（单测用）；生产默认 False。
    """
    known = set(ZH_CN)
    locations: dict = {}
    parse_errors: list[tuple[str, str]] = []
    scanned = 0
    for file_str, line_no, key in _iter_source_tr_keys(root_dir, parse_errors=parse_errors):
        scanned += 1
        if key in known:
            continue
        locations.setdefault(key, []).append((file_str, line_no))

    missing = sorted(locations.keys())
    empty = scanned == 0
    if strict and parse_errors:
        raise RuntimeError(
            f"源码解析失败 {len(parse_errors)} 个文件（缺失列表不完整）：{parse_errors[:3]}"
        )
    if strict and missing:
        raise KeyError(f"源码 tr() 缺失 {len(missing)} 个 key：{missing}")
    if strict and empty and not allow_empty:
        raise RuntimeError("源码扫描到 0 处 tr() 调用，疑似路径错误")
    return {
        "missing": missing,
        "locations": locations,
        "scanned": scanned,
        "empty": empty,
        "parse_errors": parse_errors,
    }


def validate_dict_i18n_keys(
    root_dir: Path | str | None = None,
    *,
    strict: bool = False,
) -> dict:
    """扫描 *I18N* = {k: "v"} 的字符串值，返回 {missing, locations, scanned, parse_errors}。"""
    known = set(ZH_CN)
    locations: dict = {}
    parse_errors: list[tuple[str, str]] = []
    scanned = 0
    for file_str, line_no, dict_name, key in _iter_dict_i18n_keys(
        root_dir, parse_errors=parse_errors
    ):
        scanned += 1
        if key in known:
            continue
        locations.setdefault(key, []).append((file_str, line_no, dict_name))

    missing = sorted(locations.keys())
    if strict and parse_errors:
        raise RuntimeError(
            f"源码解析失败 {len(parse_errors)} 个文件"
            f"（字典 key 缺失列表不完整）：{parse_errors[:3]}"
        )
    if strict and missing:
        raise KeyError(f"i18n 字典值缺失 {len(missing)} 个 key：{missing}")
    return {
        "missing": missing,
        "locations": locations,
        "scanned": scanned,
        "parse_errors": parse_errors,
    }


def main() -> int:
    exit_code = 0

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
            "[source] 扫描到 0 处 tr() 调用——CI 环境路径错误或所有 .py 均解析失败，不能视为通过",
            file=sys.stderr,
        )
    if src_rep["missing"]:
        exit_code = 1
        print(f"[source] 缺失 {len(src_rep['missing'])} 个 tr() key：")
        for key in src_rep["missing"]:
            refs = src_rep["locations"][key]
            suffix = " ..." if len(refs) > 3 else ""
            print(f"  {key!r} @ {refs[:3]}{suffix}")

    try:
        dict_rep = validate_dict_i18n_keys(strict=False)
    except FileNotFoundError as e:
        print(f"[dict] {e}", file=sys.stderr)
        return 1

    if dict_rep["parse_errors"]:
        exit_code = 1
        print(
            f"[dict] {len(dict_rep['parse_errors'])} 个文件解析失败"
            f"（与 [source] 重复，不重复打印）",
            file=sys.stderr,
        )

    if dict_rep["missing"]:
        exit_code = 1
        print(
            f"[dict] 缺失 {len(dict_rep['missing'])} 个 i18n 字典值 key"
            f'（*I18N* = {{k: "key"}} 的 value）：'
        )
        for key in dict_rep["missing"]:
            refs = dict_rep["locations"][key]
            suffix = " ..." if len(refs) > 3 else ""
            pretty = ", ".join(f"{f}:{ln}({name})" for f, ln, name in refs[:3])
            print(f"  {key!r} @ {pretty}{suffix}")

    try:
        fmt_rep = validate_tr_format_keys(strict=False)
    except FileNotFoundError as e:
        print(f"[format] {e}", file=sys.stderr)
        return 1

    if fmt_rep["parse_errors"]:
        exit_code = 1
        print(
            f"[format] {len(fmt_rep['parse_errors'])} 个文件解析失败（format kwargs 未参与校验）",
            file=sys.stderr,
        )

    if fmt_rep["missing"]:
        exit_code = 1
        print(f"[format] {len(fmt_rep['missing'])} 处 tr().format() 缺占位符参数：")
        for key, gap in fmt_rep["missing"].items():
            refs = fmt_rep["locations"][key]
            suffix = " ..." if len(refs) > 3 else ""
            pretty = ", ".join(f"{f}:{ln}" for f, ln in refs[:3])
            print(f"  {key!r} 缺 {gap} @ {pretty}{suffix}")

    if fmt_rep["uncertain"]:
        print(
            f"[format] {len(fmt_rep['uncertain'])} 处 tr() 占位符可能未覆盖"
            f"（调用含 **kwargs，无法静态判定）："
        )
        for key, gap in fmt_rep["uncertain"].items():
            refs = fmt_rep["locations"][key]
            suffix = " ..." if len(refs) > 3 else ""
            pretty = ", ".join(f"{f}:{ln}" for f, ln in refs[:3])
            print(f"  {key!r} 可能缺 {gap} @ {pretty}{suffix}")

    if exit_code == 0:
        print(
            f"OK（tr() {src_rep['scanned']} 处，"
            f"i18n 字典值 {dict_rep['scanned']} 处，"
            f"format kwargs {fmt_rep['scanned']} 处）"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
