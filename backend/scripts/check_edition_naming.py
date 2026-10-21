"""刊物种属词族前后端对账（#132，模式抄 check_scoring_mirror.py）。

四步检查，缺一不可：

1. **键集对账**：两侧键集合相等（只比对共同存在的键会漏掉「单边新增键」）。
2. **值对账**：frontend/src/lib/edition-naming.ts 与 backend/app/core/edition_naming.py
   的 EDITION_LABELS 逐键逐值一致。
3. **导航标签断言**：navigation.ts 受 node 沙箱限制不能 import 常量
   （check-navigation-access.js 只桩了 lucide-react），故它的三个标签
   改由断言式对账。
4. **漂移扫描**（两种）：
   - 情报族词只允许出现在两个常量文件里——调度显示名/通知文案等必须引用
     常量，否则改镜像里的词真实文案仍留旧词；
   - **旧刊名禁用表**（日报/周刊/月刊/周报）命中即红——只扫情报族词时，
     「日报」回流完全无人发现（#134 复审实锤：9 处残留与一处前后端
     分叉从门禁下溜走）。豁免路径见 FORBIDDEN_PATH_ALLOWLIST。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_LIB = REPO_ROOT / "frontend" / "src" / "lib" / "edition-naming.ts"
BACKEND_MODULE = BACKEND_ROOT / "app" / "core" / "edition_naming.py"

# 允许硬编码出现的两个真相源文件
CONSTANT_FILES = {FRONTEND_LIB.resolve(), BACKEND_MODULE.resolve()}

# navigation.ts 是例外：check-navigation-access.js 用 node 沙箱单独转译它
# （只桩了 lucide-react），引 TS 常量会破沙箱——故它的三个标签改由
# assert_navigation_labels() 断言式对账，漂移同样不可复发。
NAV_MODULE = REPO_ROOT / "frontend" / "src" / "lib" / "navigation.ts"

# 扫描范围：前端 src 与后端 app（构建产物不在其中）
SCAN_ROOTS = [REPO_ROOT / "frontend" / "src", BACKEND_ROOT / "app"]
SCAN_SUFFIXES = {".ts", ".tsx", ".py"}

# 情报族词表（与常量文件里的值一致；新增种属时同步这里）
EDITION_WORDS = ["今日情报", "每日情报", "每周情报", "每月情报", "专题情报"]

# 旧刊名禁用表：情报族落地后，日报/周刊/月刊/周报 不该再出现在用户可见文案里
# （复审根因：只扫情报族词时，「日报」回流完全无人发现——本轮就有 9 处残留
# 与一处前后端分叉从门禁下溜走）。命中即红，除非落在下面的豁免路径里。
FORBIDDEN_EDITION_WORDS = ["日报", "周刊", "月刊", "周报"]

# 豁免路径：这些是另一个产品线/内部提示词，刊名语义与情报族无关
FORBIDDEN_PATH_ALLOWLIST = (
    "novel",  # 网文周报是独立产品线
    "llm/prompts",  # LLM 内部提示词措辞
    "llm\\prompts",
    "app/models",  # ORM 层 schema 注释用的是领域术语（daily_report 表等）
    "llm_evaluations",  # LLM 评测 prompt 原文（内嵌日报/周刊措辞）
)


def parse_frontend() -> dict[str, str]:
    source = FRONTEND_LIB.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for key, value in re.findall(r"^\s*(\w+):\s*'([^']+)'", source, re.MULTILINE):
        result[key] = value
    if not result:
        raise SystemExit("FAIL 前端 edition-naming.ts 未解析到任何条目")
    return result


def parse_backend() -> dict[str, str]:
    source = BACKEND_MODULE.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for key, value in re.findall(r'^\s*"(\w+)":\s*"([^"]+)"', source, re.MULTILINE):
        result[key] = value
    if not result:
        raise SystemExit("FAIL 后端 edition_naming.py 未解析到任何条目")
    return result


def _is_test_path(path: Path) -> bool:
    """测试文件不算生产文案：断言字面值是它们的本职（穷举与单测都合法）。"""
    parts = path.parts
    if "__tests__" in parts or "tests" in parts:
        return True
    return path.name.endswith((".test.ts", ".test.tsx", "_test.py"))


def assert_navigation_labels(labels: dict[str, str]) -> list[str]:
    """导航里的三个版式标签必须等于常量表（navigation.ts 不能 import 常量）。"""
    source = NAV_MODULE.read_text(encoding="utf-8")
    failures: list[str] = []
    for key in ("daily", "weekly", "monthly"):
        match = re.search(rf"id:\s*'{key}',\s*label:\s*'([^']+)'", source)
        if not match:
            failures.append(f"navigation.ts 找不到 {key} 的 label")
            continue
        if match.group(1) != labels.get(key):
            failures.append(f"navigation.ts {key} 标签「{match.group(1)}」 != 常量表「{labels.get(key)}」")
    return failures


NAV_LABEL_PATTERN = re.compile(r"id:\s*'(daily|weekly|monthly)',\s*label:\s*'[^']+'")


def _iter_code_lines(path: Path) -> list[tuple[int, str]]:
    """产出「非注释、非文档字符串」的行（Python 的三引号块需状态机跳过）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    lines: list[tuple[int, str]] = []
    in_docstring = False
    in_block_comment = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if path.suffix == ".py":
            # 注释先判：注释里的引号不该改变 docstring 状态
            if stripped.startswith("#"):
                continue
            quotes = stripped.count('"""') + stripped.count("'''")
            if in_docstring:
                if quotes % 2 == 1:
                    in_docstring = False
                continue
            if quotes % 2 == 1:
                in_docstring = True
                continue
            if stripped.startswith(('"""', "'''")):
                continue  # 单行 docstring
        else:
            # 块注释跟踪：/* ... */ 中间行也要跳过
            if in_block_comment:
                if "*/" in line:
                    in_block_comment = False
                continue
            if stripped.startswith("/*") and "*/" not in line:
                in_block_comment = True
                continue
            if stripped.startswith(("//", "*", "/*", "{/*")):
                continue
        lines.append((lineno, line))
    return lines


def scan_hardcoded() -> list[str]:
    """两种漂移扫描：情报族词硬编码 + 旧刊名（日报/周刊/月刊/周报）回流。"""
    hits: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if path.suffix not in SCAN_SUFFIXES or not path.is_file():
                continue
            if path.resolve() in CONSTANT_FILES or _is_test_path(path):
                continue
            rel = str(path.relative_to(REPO_ROOT))
            if any(token in rel for token in FORBIDDEN_PATH_ALLOWLIST):
                continue  # 豁免路径（网文周报产品线 / LLM 内部提示词）
            is_nav = path.resolve() == NAV_MODULE.resolve()
            for lineno, line in _iter_code_lines(path):
                if is_nav and NAV_LABEL_PATTERN.search(line):
                    continue  # 导航三标签由 assert_navigation_labels 断言式对账
                for word in EDITION_WORDS:
                    if word in line:
                        hits.append(f"{rel}:{lineno} 硬编码「{word}」")
                for word in FORBIDDEN_EDITION_WORDS:
                    if word in line:
                        hits.append(f"{rel}:{lineno} 旧刊名回流「{word}」")
    return hits


def main() -> int:
    for path in (FRONTEND_LIB, BACKEND_MODULE):
        if not path.exists():
            raise SystemExit(f"FAIL 找不到镜像文件 {path}")

    frontend = parse_frontend()
    backend = parse_backend()

    failures: list[str] = []

    # 1) 键集双向
    only_frontend = sorted(set(frontend) - set(backend))
    only_backend = sorted(set(backend) - set(frontend))
    if only_frontend:
        failures.append(f"前端多出的键（后端缺）: {', '.join(only_frontend)}")
    if only_backend:
        failures.append(f"后端多出的键（前端缺）: {', '.join(only_backend)}")

    # 2) 值逐键比对
    for key in sorted(set(frontend) & set(backend)):
        if frontend[key] != backend[key]:
            failures.append(f"{key}: 前端「{frontend[key]}」 vs 后端「{backend[key]}」")

    # 3) 导航标签断言式对账（navigation.ts 受 node 沙箱限制不能 import 常量）
    failures.extend(assert_navigation_labels(frontend))

    # 4) 硬编码漂移
    for hit in scan_hardcoded():
        failures.append(f"{hit}（种属词必须引用常量）")

    if failures:
        print("FAIL 刊物种属词族口径检查未过：")
        for line in failures:
            print(f"  {line}")
        return 1

    print(
        "edition naming mirror OK:",
        ", ".join(f"{key}={frontend[key]}" for key in sorted(frontend)),
        "| 硬编码扫描 0 命中",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
