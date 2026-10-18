#!/usr/bin/env python3
"""分层纪律的机器强制检查（对应 AGENTS.md「Layering Discipline」）。

机器化 AGENTS.md 里*符号级、可无歧义判定*的禁止项，作用于两个目录：

**app/api/v1/**（两条）：

1. 禁止 import sqlalchemy —— 例外：`sqlalchemy.ext.asyncio`（AsyncSession 类型注解）
   与 `sqlalchemy.exc`（IntegrityError / OperationalError 等异常类，供 try/except）。
2. 禁止在 api 层直接写 ORM 查询：`select()/insert()/update()/delete()` 构造，
   以及 `db.execute(...) / db.add(...) / db.scalars(...) / db.scalar(...)`。
   这些必须下沉到 `repositories/`。

**app/repositories/**（一条，#113）：

3. 禁止 import `app.services.*` —— 依赖方向 repositories→services 逆向
   （函数内局部 import 同样抓：#113 的违例全部藏在函数体内）。
   已知存量豁免走 `REPO_SERVICES_IMPORT_ALLOWLIST`（按文件+模块粒度，
   引用重构 issue，棘轮式收缩，只减不增）。

**不检查**的项（因为是符号级且和允许项同模块，自动判定会大量误报）：
`from app.models import <ORMModel>` 与 `<ORMModel>` 混在 Enum / User 依赖注入里的情况，
仍靠 AGENTS.md 2.2 分层表「禁止」列的人工评审兜底。

用法：
    python scripts/check_layering.py            # 检查 api/v1 + repositories
    python scripts/check_layering.py app/api/v1 # 只检查指定目录（api 规则）

命中违规时打印文件:行 + 说明并以退出码 1 结束，供 CI 阻断。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# 检查目标目录（相对 backend/）。
API_DIR = Path("app/api/v1")
REPO_DIR = Path("app/repositories")

# 刻意豁免的文件名（分层的合法低层边界）。
# _db_write.py 不再需要豁免——SQLite PRAGMA 调用已随 SQLite 分支移除。
ALLOWLIST: set[str] = set()

# repositories→services 禁令的存量豁免（#113 收口时遗留，#122 重构后清空）。
# 键 = 文件名，值 = 允许 import 的 app.services 模块前缀集合；
# 新增条目必须附带 issue 引号，且只允许删除、不允许新增（棘轮）。
REPO_SERVICES_IMPORT_ALLOWLIST: dict[str, set[str]] = {
    # analysis_repo 评分编排上移 services 的重构单：#122
    "analysis_repo.py": {"app.services.feedback_signal", "app.services.scoring_engine"},
}

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


def check_repo_services_imports(path: Path) -> list[str]:
    """repositories 层文件：禁止 import app.services.*（allowlist 内的前缀除外）。

    ast.walk 覆盖模块级与函数体内的 import——#113 的违例全部藏在函数体里，
    只查模块级会漏。
    """
    allowed_prefixes = REPO_SERVICES_IMPORT_ALLOWLIST.get(path.name, set())
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def _violation(lineno: int, desc: str) -> None:
        if any(desc == prefix or desc.startswith(prefix + ".") for prefix in allowed_prefixes):
            return
        violations.append(
            f"{path}:{lineno}: 禁止 `{desc}`——repositories 层不得 import services"
            f"（业务编排属于 service，口径常量在 app/core/；存量豁免只减不增）"
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app.services" or module.startswith("app.services."):
                _violation(node.lineno, module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.services" or alias.name.startswith("app.services."):
                    _violation(node.lineno, alias.name)

    return violations


def main(argv: list[str]) -> int:
    # legacy 单目录模式只跑 api 规则（保持既有用法兼容）；默认双目录全查。
    targets = [(Path(argv[1]), "api")] if len(argv) > 1 else [(API_DIR, "api"), (REPO_DIR, "repo")]

    all_violations: list[str] = []
    file_count = 0
    for target, kind in targets:
        if not target.exists():
            print(f"ERROR: 目录不存在: {target}（请在 backend/ 下运行）", file=sys.stderr)
            return 2
        files = sorted(p for p in target.glob("*.py") if p.name not in ALLOWLIST)
        file_count += len(files)
        for path in files:
            if kind == "api":
                all_violations.extend(check_file(path))
            else:
                all_violations.extend(check_repo_services_imports(path))

    if all_violations:
        print("分层违规（详见 AGENTS.md「Layering Discipline」）：", file=sys.stderr)
        for line in all_violations:
            print(f"  {line}", file=sys.stderr)
        print(
            f"\n共 {len(all_violations)} 处违规，跨 {len({v.split(':')[0] for v in all_violations})} 个文件。",
            file=sys.stderr,
        )
        return 1

    scopes = " + ".join(str(t) for t, _ in targets)
    print(f"分层检查通过：{scopes} 共 {file_count} 个文件，无禁用 import / 逆向依赖。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
