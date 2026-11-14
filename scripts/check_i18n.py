# file: check_i18n.py
# coding: utf-8
"""i18n key 检查：源码 tr() 字面量 + i18n 字典值 + tr().format() 参数。

单语言（简体中文）项目：不再校验"语言包之间"的一致性——语言注册表
与 validate_keys 已随多语言支持一并移除。本脚本只保证源码中引用的
key 都在 ZH_CN 中定义。

新增字典扫描的原因：`_REASON_I18N_KEYS = {"k": "update.reason.k"}` 这类
"key 存字典、用时 tr(变量)"的写法，`tr("字面量")` 扫描器看不到值，
新增 reason 忘加翻译时 CI 会假绿。命名约定 `*I18N*` 的模块级 dict
纳入扫描，覆盖该盲点。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator, Union

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    # 直接 `python scripts/check_i18n.py` 运行时，脚本目录是 scripts/，
    # 项目根不在 sys.path；需要显式把 src 加进来才能 import desktop_calendar。
    sys.path.insert(0, str(_SRC))

from desktop_calendar.config.translations import ZH_CN  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

__all__ = [
    "validate_source_keys", "validate_dict_i18n_keys",
    "validate_tr_format_keys", "_iter_source_tr_keys", "_iter_dict_i18n_keys",
    "_iter_tr_format_calls", "_placeholders", "main",
]
# 模块级 i18n 字典命名约定：变量名含 I18N（如 _REASON_I18N_KEYS / I18N_MAP）。
# 不用宽松的 "_KEYS" 匹配，避免误扫 qss._MSG_KEYS 等非 i18n 字典。
_I18N_DICT_NAME_RE = re.compile(r"(^|_)I18N(_|$)")

# ===================== 占位符提取（本地实现） =====================
# 检查工具不依赖 i18n.py 的私有实现，避免"i18n.py 重构 → 检查脚本坏掉"
# 的隐性耦合。正则与 i18n.py 曾用的一致：只匹配 \w+ 形式的命名占位符，
# 本项目翻译文本不使用 {{ }} 转义，故不处理该情况。
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _placeholders(text: str) -> set:
    """返回文本中所有 {name} 占位符的名字集合。"""
    return set(_PLACEHOLDER_RE.findall(text or ""))


# ===================== 源码扫描基础设施 =====================
def _default_src_root() -> Path:
    """默认扫描路径：src/desktop_calendar。"""
    return _SRC / "desktop_calendar"


def _iter_py_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _iter_ast_trees(
    root_dir: Union[Path, str, None],
    parse_errors: list[tuple[str, str]] | None = None,
) -> Iterator[tuple[str, ast.AST]]:
    """遍历 root 下所有 .py，yield (路径字符串, AST)。

    解析失败的文件追加到 parse_errors（若提供）后跳过——
    否则语法坏文件里的 tr() 会漏扫。root 不存在时抛 FileNotFoundError
    （而非静默 return），避免 CI 在路径错误时"扫描 0 处 tr()"假绿。
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
        yield str(py_file), tree


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
    """
    for file_str, tree in _iter_ast_trees(root_dir, parse_errors):
        for node in ast.walk(tree):
            if not _is_tr_call(node) or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                yield file_str, node.lineno, first.value


def _i18n_dict_name(node: ast.AST) -> str | None:
    """若 node 是 `NAME = {dict}` 或 `NAME: T = {dict}` 且 NAME 含 I18N，
    返回 NAME；否则 None。

    同时处理 ast.Assign 与 ast.AnnAssign：类型注解不影响字典扫描，
    但漏掉 AnnAssign 会让 `_X_I18N_Y: dict[str, str] = {...}` 被跳过。
    """
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
    root_dir: Union[Path, str, None] = None,
    *,
    parse_errors: list[tuple[str, str]] | None = None,
) -> Iterator[tuple[str, int, str, str]]:
    """迭代源码中 `*I18N* = {k: "v"}` 字典的字符串值。

    yield (文件路径, 行号, 变量名, key)。只看 value 为 str 常量的项，
    跳过 tuple / 数字 / 嵌套 dict 等非 i18n 值。

    命名约定的语义：`*I18N*` 字典的 value 必须是 module-level i18n
    key（即必须出现在 ZH_CN 中）。若未来需要"含 I18N 但 value 不是
    key"的字典（如 I18N_FEATURE_FLAGS = {"x": "enabled"}），应改用
    其他命名，避免被本函数误报。
    """
    for file_str, tree in _iter_ast_trees(root_dir, parse_errors):
        for node in ast.walk(tree):
            name = _i18n_dict_name(node)
            if name is None:
                continue
            # node.value 已保证是 ast.Dict（_i18n_dict_name 内检查）
            for v in node.value.values:
                if not (isinstance(v, ast.Constant)
                        and isinstance(v.value, str)):
                    continue
                if not v.value:
                    continue
                yield file_str, v.lineno, name, v.value


# ===================== tr().format() 参数覆盖校验 =====================
# 覆盖盲点：源码 tr("k").format(...) / tr("k", **kw) 漏传占位符时
# tr() 会返回未替换原文，用户看到 {max_day}。这里静态扫描调用点，
# 比对 kwargs 名集合是否覆盖 ZH_CN[k] 的占位符。

def _build_parent_map(tree: ast.AST) -> dict:
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _iter_tr_format_calls(
    root_dir: Union[Path, str, None] = None,
    *,
    parse_errors: list[tuple[str, str]] | None = None,
) -> Iterator[tuple[str, int, str, set, bool]]:
    """迭代 tr("k").format(**kw) / tr("k", **kw) 调用。

    yield (文件, 行号, key, 明确 kwargs 名集合, has_star)。
    has_star=True 表示调用里含 `**kwargs` 展开：明确 kwargs 仍参与
    校验，但"未覆盖的占位符"可能由展开补上，调用方应降级为
    uncertain 而非 missing。

    无法静态确定 key（变量 / f-string）时整个调用跳过。
    本函数不覆盖 `format_map` / `replace` 等其它字符串格式化方式，
    当前项目约定只用 `format`；若未来引入其它方式，需在此扩展。
    """
    for file_str, tree in _iter_ast_trees(root_dir, parse_errors):
        parents = _build_parent_map(tree)

        for node in ast.walk(tree):
            if not _is_tr_call(node) or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant)
                    and isinstance(first.value, str)):
                continue
            key = first.value

            # 形态 1：tr("k").format(x=1, ...)
            parent = parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.attr == "format":
                grand = parents.get(parent)
                if isinstance(grand, ast.Call):
                    explicit = {kw.arg for kw in grand.keywords if kw.arg}
                    has_star = any(
                        kw.arg is None for kw in grand.keywords)
                    yield (file_str, grand.lineno, key,
                           explicit, has_star)
                    continue

            # 形态 2：tr("k", x=1, ...)
            if node.keywords:
                explicit = {kw.arg for kw in node.keywords if kw.arg}
                has_star = any(kw.arg is None for kw in node.keywords)
                yield (file_str, node.lineno, key, explicit, has_star)


def validate_tr_format_keys(
    root_dir: Union[Path, str, None] = None,
    *,
    strict: bool = False,
) -> dict:
    """校验 tr().format() / tr(..., **kw) 是否覆盖占位符。

    返回结构：
        {
          "missing":   {key: [缺失占位符, ...]},   # 无 ** 展开，确定缺失
          "uncertain": {key: [可能缺失, ...]},     # 含 ** 展开，无法静态判定
          "locations": {key: [(file, line), ...]},
          "scanned":   int,
          "parse_errors": [(file, reason), ...],
        }

    只对"key 存在于 ZH_CN"的调用校验；未定义 key 由
    validate_source_keys 报，避免重复噪音。

    含 `**kwargs` 的调用：明确 kwargs 仍参与校验，未覆盖的占位符
    记为 uncertain 而非 missing —— `**` 可能在运行时补上，静态
    判定不了。但"明确写了 days 却拼成 day"这类错误仍会被抓：day
    不在 explicit 里，gap 包含 days，进 uncertain（strict 下仍只
    报 missing，uncertain 由调用方决定是否警告）。

    strict=True 时：parse_errors / missing 抛异常；uncertain 不抛，
    因为 `**` 的存在让"缺失"无法静态确定，误报会逼调用方把 i18n
    参数从 `**extra` 里拆出来，破坏合理封装。
    """
    known = set(ZH_CN)
    missing: dict = {}
    uncertain: dict = {}
    locations: dict = {}
    parse_errors: list[tuple[str, str]] = []
    scanned = 0

    for file_str, line_no, key, kwargs, has_star in _iter_tr_format_calls(
            root_dir, parse_errors=parse_errors):
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
            f"（format kwargs 校验不完整）：{parse_errors[:3]}")
    if strict and missing:
        raise KeyError(
            f"tr().format() 缺少占位符参数 {len(missing)} 处：{missing}")

    return {
        "missing": {k: sorted(v) for k, v in missing.items()},
        "uncertain": {k: sorted(v) for k, v in uncertain.items()},
        "locations": locations,
        "scanned": scanned,
        "parse_errors": parse_errors,
    }


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
    # 先报 parse_errors：有文件没扫描成功时，missing 列表本身不完整，
    # 先报缺失会掩盖"还有文件未参与校验"这个更根本的问题。
    if strict and parse_errors:
        raise RuntimeError(
            f"源码解析失败 {len(parse_errors)} 个文件"
            f"（缺失列表不完整）：{parse_errors[:3]}")
    if strict and missing:
        raise KeyError(
            f"源码 tr() 缺失 {len(missing)} 个 key：{missing}")
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
    root_dir: Union[Path, str, None] = None,
    *,
    strict: bool = False,
) -> dict:
    """扫描 `*I18N* = {k: "v"}` 字典的字符串值，返回缺失 key 报告。

    返回结构：

        {
          "missing":   sorted list[str]
          "locations": {key: [(file, line, dict_name), ...]}
          "scanned":   int
          "parse_errors": [(file, reason), ...]
        }

    与 validate_source_keys 的区别：
      - 没有 "empty" 字段：项目可能完全没有 i18n 字典，属合法状态，
        main() 不因 scanned == 0 报错。
      - strict=True 且 missing 时抛 KeyError；parse_errors 时抛
        RuntimeError（与 source 扫描一致，因为缺文件同样让结果不完整）。
    """
    known = set(ZH_CN)
    locations: dict = {}
    parse_errors: list[tuple[str, str]] = []
    scanned = 0
    for file_str, line_no, dict_name, key in _iter_dict_i18n_keys(
            root_dir, parse_errors=parse_errors):
        scanned += 1
        if key in known:
            continue
        locations.setdefault(key, []).append((file_str, line_no, dict_name))

    missing = sorted(locations.keys())
    if strict and parse_errors:
        raise RuntimeError(
            f"源码解析失败 {len(parse_errors)} 个文件"
            f"（字典 key 缺失列表不完整）：{parse_errors[:3]}")
    if strict and missing:
        raise KeyError(
            f"i18n 字典值缺失 {len(missing)} 个 key：{missing}")
    return {
        "missing": missing,
        "locations": locations,
        "scanned": scanned,
        "parse_errors": parse_errors,
    }


# ===================== CLI =====================
def main() -> int:
    exit_code = 0

    # 语言包一致性校验（validate_keys）已随多语言支持移除；
    # 单语言项目只需保证源码引用的 key 都在 ZH_CN 中定义。

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

    # ---- i18n 字典值扫描 ----
    try:
        dict_rep = validate_dict_i18n_keys(strict=False)
    except FileNotFoundError as e:
        print(f"[dict] {e}", file=sys.stderr)
        return 1

    if dict_rep["parse_errors"]:
        # 与 source 扫描共用同一批文件，解析错误已在上面报过；
        # 这里只更新 exit_code，避免重复刷屏。
        exit_code = 1
        print(
            f"[dict] {len(dict_rep['parse_errors'])} 个文件解析失败"
            f"（与 [source] 重复，不重复打印）",
            file=sys.stderr)

    if dict_rep["missing"]:
        exit_code = 1
        print(
            f"[dict] 缺失 {len(dict_rep['missing'])} 个 i18n 字典值 key"
            f"（*I18N* = {{k: \"key\"}} 的 value）：")
        for key in dict_rep["missing"]:
            refs = dict_rep["locations"][key]
            suffix = " ..." if len(refs) > 3 else ""
            pretty = ", ".join(
                f"{f}:{ln}({name})" for f, ln, name in refs[:3])
            print(f"  {key!r} @ {pretty}{suffix}")

    # ---- tr().format() 参数覆盖扫描 ----
    try:
        fmt_rep = validate_tr_format_keys(strict=False)
    except FileNotFoundError as e:
        print(f"[format] {e}", file=sys.stderr)
        return 1

    if fmt_rep["parse_errors"]:
        exit_code = 1
        print(
            f"[format] {len(fmt_rep['parse_errors'])} 个文件解析失败"
            f"（format kwargs 未参与校验）", file=sys.stderr)

    if fmt_rep["missing"]:
        exit_code = 1
        print(f"[format] {len(fmt_rep['missing'])} 处 tr().format() 缺占位符参数：")
        for key, gap in fmt_rep["missing"].items():
            refs = fmt_rep["locations"][key]
            suffix = " ..." if len(refs) > 3 else ""
            pretty = ", ".join(f"{f}:{ln}" for f, ln in refs[:3])
            print(f"  {key!r} 缺 {gap} @ {pretty}{suffix}")

    if fmt_rep["uncertain"]:
        # 含 **kwargs 展开的调用：明确 kwargs 覆盖不了，但运行时可能
        # 由展开补上。打印警告但不置 exit_code —— 误报会逼调用方把
        # i18n 参数从 **extra 里拆出来，反而破坏合理封装。
        print(
            f"[format] {len(fmt_rep['uncertain'])} 处 tr() 占位符可能未覆盖"
            f"（调用含 **kwargs，无法静态判定）：")
        for key, gap in fmt_rep["uncertain"].items():
            refs = fmt_rep["locations"][key]
            suffix = " ..." if len(refs) > 3 else ""
            pretty = ", ".join(f"{f}:{ln}" for f, ln in refs[:3])
            print(f"  {key!r} 可能缺 {gap} @ {pretty}{suffix}")

    if exit_code == 0:
        print(
            f"OK（tr() {src_rep['scanned']} 处，"
            f"i18n 字典值 {dict_rep['scanned']} 处，"
            f"format kwargs {fmt_rep['scanned']} 处）")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())