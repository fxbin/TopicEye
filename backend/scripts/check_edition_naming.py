"""刊物种属词族前后端对账（#132，模式抄 check_scoring_mirror.py）。

三道检查，缺一不可：

1. **值对账**：frontend/src/lib/edition-naming.ts 与 backend/app/core/edition_naming.py
   的 EDITION_LABELS 逐键逐值一致。
2. **键集对账**：两侧键集合相等（只比对共同存在的键会漏掉「单边新增键」）。
3. **硬编码扫描**：情报族词只允许出现在两个常量文件里；调度显示名/通知文案等
   必须引用常量——否则改镜像里的词，真实文案仍留旧词，漂移无人拦
   （前科：AI 日报/AI 周刊/全行业信息日报 三种口径并存八处分裂）。
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

# 扫描范围：前端 src 与后端 app（构建产物不在其中）
SCAN_ROOTS = [REPO_ROOT / "frontend" / "src", BACKEND_ROOT / "app"]
SCAN_SUFFIXES = {".ts", ".tsx", ".py"}

# 情报族词表（与常量文件里的值一致；新增种属时同步这里）
EDITION_WORDS = ["今日情报", "每日情报", "每周情报", "每月情报", "专题情报"]


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


def scan_hardcoded() -> list[str]:
    """情报族词出现在常量文件之外即为漂移（注释行与测试文件不计）。"""
    hits: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if path.suffix not in SCAN_SUFFIXES or not path.is_file():
                continue
            if path.resolve() in CONSTANT_FILES or _is_test_path(path):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith(("#", "//", "*", "/*")):
                    continue  # 注释不计
                for word in EDITION_WORDS:
                    if word in line:
                        hits.append(f"{path.relative_to(REPO_ROOT)}:{lineno} 硬编码「{word}」")
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

    # 3) 硬编码漂移
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
