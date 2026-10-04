#!/usr/bin/env python3
"""AGENTS.md 事实性引用的机器校验（对应 AGENTS.md「AGENTS.md 即模型接口」）。

本文件是喂给 agent 的指令文件，命令与路径过期比普通文档严重一档：agent 会照着
跑，路径失效就是静默的错误。手工核对不可持续（改文档时没人会重跑一遍），故机器化。

检查两类可无歧义判定的引用：
1. **仓库内文件路径** —— `code` 包裹的 `a/b.py`、`a/b.sh` 等，存在则通过。
2. **Makefile 目标** —— `make xxx` 形式，`Makefile` 里有同名目标则通过。

**不检查**：命令行为是否正确、脚本是否可执行、CI 作业名、目录/包名一类的软引用。
CI 作业名原本在检查范围内，实测三次都不可靠：`security-scan` 与分支名
`issue-4-cryptography-50` 同形，靠措辞、依赖链上下文、排除前缀逐一打补丁后仍同时
误报与漏报。一个会误报的门禁比没有更糟——它训练 agent 忽略检查结果，故已移除，
CI 作业名改为人工核对。判定不了的留给人工，也不在这份文件里制造假信心。

用法：
    python scripts/check_agent_docs.py            # 检查默认文件
    python scripts/check_agent_docs.py AGENTS.md  # 指定文件

命中失效引用时打印来源行号 + 失效内容，并以退出码 1 结束，供 CI 阻断。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOC = REPO_ROOT / "AGENTS.md"
MAKEFILE = REPO_ROOT / "Makefile"

# 路径引用：必须形如 `dir/name.ext`（含斜杠）或纯文件名带已知后缀。
# 排除下列形态，它们是行内代码的术语说明而非仓库内路径：
#   - `select/insert/update/delete`、`db.execute/db.add` —— 构造器与函数名列举
#   - `__init__.py` —— 常出现在「该目录**无** __init__.py」的反例说明里
#   - `package.json` —— 指 frontend/ 下的，文档未写全路径
PATH_RE = re.compile(
    r"`([A-Za-z0-9_.-]+/[A-Za-z0-9_.@-]+/[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)*/?|[A-Za-z0-9_.-]+/[A-Za-z0-9_.@-]+\.(?:py|sh|md|yml|yaml|toml|lock))`"
)
MAKE_RE = re.compile(r"`make ([a-z][a-z0-9-]*)`")

# 真实的代码/配置扩展名白名单。用于排除 `db.scalar` 这类「看着像扩展名的方法名」。
CODE_SUFFIXES = {"py", "sh", "md", "yml", "yaml", "toml", "lock"}


def is_test_placeholder(value: str) -> bool:
    """形如 `<changed-python-files>`、`tests/` 的占位，不是真实路径。"""
    return value.startswith("<") or value.endswith("/") or "..." in value


def check_paths(doc_text: str, doc_path: Path) -> list[str]:
    problems = []
    for lineno, line in enumerate(doc_text.splitlines(), 1):
        for match in PATH_RE.finditer(line):
            raw = match.group(1)
            if is_test_placeholder(raw):
                continue
            base = raw.rstrip("/")
            # 只检查带文件后缀的引用。`select/insert/update/delete`、
            # `db.execute/db.add` 这类是术语列举，没有后缀，一并排除——
            # 仓库内真实路径总带扩展名。
            leaf = base.rsplit("/", 1)[-1]
            if "." not in leaf:
                continue
            # 扩展名必须在白名单内。`db.execute/db.add/db.scalar` 的末段是
            # `db.scalar`，看着像扩展名其实是方法名——只认真实的代码/配置后缀。
            if leaf.rsplit(".", 1)[-1].lower() not in CODE_SUFFIXES:
                continue
            candidates = [REPO_ROOT / base, doc_path.parent / base]
            # AGENTS.md 里 `app/...` `tests/...` `alembic/...` 是相对 backend/ 写的简写
            candidates.append(REPO_ROOT / "backend" / base)
            if any(c.exists() for c in candidates):
                continue
            problems.append(f"  L{lineno}: 路径不存在 -> {base}")
    return problems


def check_make_targets(doc_text: str) -> list[str]:
    if not MAKEFILE.exists():
        return []
    make_text = MAKEFILE.read_text(encoding="utf-8")
    targets = set(re.findall(r"^([a-z][a-z0-9-]*):", make_text, re.MULTILINE))
    problems = []
    seen: set[str] = set()
    for tgt in MAKE_RE.findall(doc_text):
        if tgt in targets or tgt in seen:
            continue
        seen.add(tgt)
        problems.append(f"  `make {tgt}` —— Makefile 里没有这个目标")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 AGENTS.md 的事实性引用")
    parser.add_argument("doc", nargs="?", default=str(DEFAULT_DOC), help="待检查的文档")
    args = parser.parse_args()

    doc_path = Path(args.doc).resolve()
    if not doc_path.exists():
        print(f"找不到文档：{doc_path}", file=sys.stderr)
        return 1
    doc_text = doc_path.read_text(encoding="utf-8")

    problems: list[str] = []
    problems += check_paths(doc_text, doc_path)
    problems += check_make_targets(doc_text)

    if problems:
        print(f"AGENTS.md 引用校验未通过（{len(problems)} 项）：")
        for p in problems:
            print(p)
        return 1

    print("AGENTS.md 引用校验通过：路径、make 目标均存在。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
