#!/usr/bin/env python3
"""分层纪律的机器强制检查（对应 AGENTS.md「Layering Discipline」）。

只机器化 AGENTS.md 里*符号级、可无歧义判定*的两条禁止项，作用于 `app/api/v1/`：

1. 禁止 import sqlalchemy —— 例外：`sqlalchemy.ext.asyncio`（AsyncSession 类型注解）
   与 `sqlalchemy.exc`（IntegrityError / OperationalError 等异常类，供 try/except）。
2. 禁止在 api 层直接写 ORM 查询：`select()/insert()/update()/delete()` 构造，
   以及 `db.execute(...) / db.add(...) / db.scalars(...) / db.scalar(...)`。
   这些必须下沉到 `repositories/`。

**不检查**的项（因为是符号级且和允许项同模块，自动判定会大量误报）：
`from app.models import <ORMModel>` 与 `<ORMModel>` 混在 Enum / User 依赖注入里的情况，
仍靠 AGENTS.md 的人工评审 checklist 兜底。

ALLOWLIST：`_db_write.py` 是刻意的 SQLite 低层写入助手（PRAGMA busy_timeout 用
`text()` + `db.execute`），是分层的合法边界，豁免。

用法：
    python scripts/check_layering.py            # 检查默认目录
    python scripts/check_layering.py app/api/v1 # 指定目录

命中违规时打印文件:行 + 说明并以退出码 1 结束，供 CI 阻断。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# 检查目标目录（相对 backend/）。
API_DIR = Path("app/api/v1")

# 刻意豁免的文件名（分层的合法低层边界）。
ALLOWLIST = {"_db_write.py"}

# 允许的 sqlalchemy 子模块前缀（值对象 / 类型注解 / 异常类）。
ALLOWED_SQLALCHEMY_PREFIXES = ("sqlalchemy.ext.asyncio", "sqlalchemy.exc")

# 禁止在 api 层直接调用的 ORM 查询构造函数名。
FORBIDDEN_QUERY_FUNCS = {"select", "insert", "update", "delete"}

# 禁止在 api 层直接调用的 session 写/查方法（作用于名为 db 的会话）。
FORBIDDEN_SESSION_METHODS = {"execute", "add", "scalars", "scalar"}


def _import_is_allowed(module: str) -> bool:
    """`import sqlalchemy...` 是否落在允许例外内。"""
    if module == "sqlalchemy" or module.startswith("sqlalchemy."):
        return module.startswith(ALLOWED_SQLALCHEMY_PREFIXES)
    return True  # 非 sqlalchemy 的 import 一律放行


def check_file(path: Path) -> list[str]:
    """返回该文件的违规描述列表（空列表表示合规）。"""
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in ast.walk(tree):
        # ── import sqlalchemy / from sqlalchemy import ... ──
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _import_is_allowed(alias.name):
                    violations.append(
                        f"{path}:{node.lineno}: 禁止 `import {alias.name}`"
                        f"（api 层仅允许 AsyncSession 类型注解 / sqlalchemy.exc 异常类）"
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if not _import_is_allowed(module):
                names = ", ".join(a.name for a in node.names)
                violations.append(
                    f"{path}:{node.lineno}: 禁止 `from {module} import {names}`"
                    f"（api 层仅允许 AsyncSession 类型注解 / sqlalchemy.exc 异常类）"
                )

        # ── ORM 查询调用 ──
        elif isinstance(node, ast.Call):
            func = node.func
            # select(...) / insert(...) / update(...) / delete(...)
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_QUERY_FUNCS:
                violations.append(
                    f"{path}:{node.lineno}: 禁止在 api 层直接调用 `{func.id}(...)`，请下沉到 repositories/"
                )
            # db.execute(...) / db.add(...) / db.scalars(...) / db.scalar(...)
            elif (
                isinstance(func, ast.Attribute)
                and func.attr in FORBIDDEN_SESSION_METHODS
                and isinstance(func.value, ast.Name)
                and func.value.id == "db"
            ):
                violations.append(
                    f"{path}:{node.lineno}: 禁止在 api 层直接调用 `db.{func.attr}(...)`，请下沉到 repositories/"
                )

    return violations


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else API_DIR
    if not target.exists():
        print(f"ERROR: 目录不存在: {target}（请在 backend/ 下运行）", file=sys.stderr)
        return 2

    all_violations: list[str] = []
    files = sorted(p for p in target.glob("*.py") if p.name not in ALLOWLIST)
    for path in files:
        all_violations.extend(check_file(path))

    if all_violations:
        print("分层违规（详见 AGENTS.md「Layering Discipline」）：", file=sys.stderr)
        for line in all_violations:
            print(f"  {line}", file=sys.stderr)
        print(
            f"\n共 {len(all_violations)} 处违规，跨 {len({v.split(':')[0] for v in all_violations})} 个文件。",
            file=sys.stderr,
        )
        return 1

    print(f"分层检查通过：{len(files)} 个 api/v1 文件无直接 ORM 查询 / 禁用 import。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
