# Agent Guidelines

## Commit Discipline

Follow the existing project history. Recent commits use concise Conventional
Commit-style messages with Chinese summaries:

```text
fix(auth): 降低登录链路 SQLite 写锁等待
fix(cache): 重试统计工作台启动预热
fix(trending): 合并重复信源筛选项
```

Use this shape for new commits:

```text
<type>(<scope>): <中文说明>
```

Preferred types:

- `fix`: bug fixes, permission changes, UI behavior corrections, config safety fixes
- `feat`: user-visible new capability
- `chore`: tooling, scripts, repository hygiene, non-product maintenance
- `test`: tests only
- `docs`: documentation only

Preferred scopes:

- `auth`, `cache`, `trending`, `backend`, `frontend`, `config`, `db`, `docs`, `test`

## Commit Boundaries

- Keep each commit focused on one user-visible behavior, risk boundary, or maintenance concern.
- Do not mix backend, frontend, docs, and config changes unless they are required for the same fix.
- Put tests in the same commit as the behavior they verify.
- Keep local-only files out of commits, especially `backend/.env`, databases, venvs, caches, screenshots, and generated browser artifacts.
- Stage explicit paths. Avoid `git add -A` when the worktree contains unrelated or user-owned changes.

## Before Committing

Inspect the staged diff:

```bash
git diff --cached --stat
git diff --cached --summary
```

Run the smallest relevant verification:

- Backend Python syntax: `python -m py_compile <changed-python-files>`
- Backend tests: `python -m pytest <relevant-tests> -q`
- Shell scripts: `bash -n <script>`
- Frontend type check: `cd frontend && npx tsc --noEmit`
- Full quality gate (manual): `make lint`（ruff + 分层检查 + 前端类型检查）

Note: `frontend` currently has an `npm run lint` script that invokes `next lint`,
which may fail under the installed Next.js version by treating `lint` as a
project directory. Prefer `npx tsc --noEmit` unless the lint script is fixed.

## Rewriting Local Commits

If asked to adjust recent commits:

- First confirm the worktree is clean.
- Create a backup branch before rewriting, for example:

```bash
git branch backup/recent-before-rewrite HEAD
```

- Preserve the final file tree unless the user explicitly asks for content changes.
- After rewriting, compare with the backup branch:

```bash
git diff backup/recent-before-rewrite..HEAD
```

An empty diff means the rewrite only changed commit history, not project content.

## Commit Examples

Good:

```text
fix(auth): 登录页隐藏应用导航
fix(auth): 移出默认管理员种子凭据
fix(backend): 整理后端根目录诊断脚本
docs: 补充 agent 提交规范
```

Avoid:

```text
Update stuff
Fix bugs
Move admin seed credentials to env
Deduplicate trending source filters
```

## Layering Discipline

后端依赖方向（严格单向，禁止逆向或跨层）：

```text
api/v1/ ──► services/ ──► repositories/ ──► models/ ──► sqlalchemy
```

### 各层职责与禁止事项

| 层 | 允许 | 禁止 |
|---|---|---|
| `api/v1/` | 路由声明、请求校验、调用 service / repository、response shaping | `import sqlalchemy`（例外：`AsyncSession` 仅作类型注解可保留）；`from app.models import <ORMModel>`（ORM 模型类）；直接 `select(...)` / `db.execute(...)` / `db.add(...)` |
| `services/` | 业务编排、事务边界、调用 repository、跨 repo 组合 | 无（允许直接 import sqlalchemy / app.models） |
| `repositories/` | ORM 唯一入口，CRUD + 复杂查询封装，继承 `BaseRepository[ModelType]` 或独立类 | 互相 `import`（repo 之间不依赖）；写业务逻辑（业务逻辑属于 service） |
| `models/` | 纯 ORM 声明、字段定义、`__table_args__` | 业务方法、副作用、IO 操作 |
| `schemas/` | Pydantic 请求/响应模型、序列化 | ORM import、DB 访问 |

### 例外清单

- `app.models.<X>` 中的 **Enum 类**（如 `SourceStatus`、`ContentStatus`、`FavoriteTargetType`）允许 api 层 import，因为它们是值对象而非 ORM 模型。
- `AsyncSession` 作 FastAPI 依赖注入的类型注解允许 api 层 import（`from sqlalchemy.ext.asyncio import AsyncSession`）。
- `app.core.database.get_db` 作 FastAPI 依赖允许 api 层 import。
- `IntegrityError` 等异常类允许 api 层 import（用于 try/except 捕获）。

### 存量违规与迁移策略

`api/v1/` 层的**硬违规（直接写 ORM 查询）已基本清零**：目前仅剩 `_db_write.py`
一处刻意保留（SQLite 低层写入助手，PRAGMA busy_timeout 用 `text()` + `db.execute`），
它是分层的合法边界，已在检查中豁免。剩余的 `import sqlalchemy` 绝大多数是
`AsyncSession` 类型注解与 `sqlalchemy.exc` 异常类等**已列入例外**的用法。

**机器强制**：`select/insert/update/delete` 构造与 `db.execute/db.add/db.scalars/db.scalar`
出现在 `api/v1/*.py` 会被 CI 的 `backend-layering` 作业阻断（本地跑 `make layering`
或 `python scripts/check_layering.py`），无需再靠人工数文件。符号级的
`from app.models import <ORMModel>`（ORM 模型类混在 Enum/User 依赖里）因与允许项同模块，
自动判定会误报，仍靠下面的评审 checklist 兜底。

迁移策略（仍适用于符号级存量清理）：

1. **新增代码必须遵循分层约束**，PR 评审时强制检查。
2. **存量按风险等级打包迁移**，每个 commit 迁移 3-5 个相关的 api 文件（避免单 commit 过碎、也避免大批量混合）。打包维度：同类查询模式（如纯 list / 含 JOIN / 含聚合）或同业务域（如 trending 系列）。
3. **迁移优先级**：含复杂 JOIN / 子查询 / N+1 的 endpoint 优先；纯 `get_by_id` 类简单查询可后迁。
4. 迁移时行为必须完全等价，**不优化性能、不改变返回字段**，避免混合关注点。

### 评审 checklist

提交前自查 3 条：

- [ ] 新增的 `api/v1/*.py` 是否 import 了 `sqlalchemy`（除 `AsyncSession` 类型注解）或 `app.models.<ORMModel>`？
- [ ] 新增的 ORM 查询（`select` / `db.execute` / `db.add`）是否在 `api/v1/*.py` 中？如在，必须下沉到 `repositories/`。
- [ ] 新增的 `repositories/*.py` 是否互相 `import`？如在，必须拆解或合并到同一 repo。

### 示例

**违规**（api 层直接写 ORM 查询）：

```python
# app/api/v1/topics.py
from sqlalchemy import select, func
from app.models.topic import TopicGroup

@router.get("")
async def list_topics(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TopicGroup).order_by(TopicGroup.best_score.desc()))
    return {"items": result.scalars().all()}
```

**合规**（下沉到 repo）：

```python
# app/repositories/topic_repo.py
class TopicRepository(BaseRepository[TopicGroup]):
    model = TopicGroup

    async def list_ordered_by_best_score(self) -> Sequence[TopicGroup]:
        stmt = select(TopicGroup).order_by(TopicGroup.best_score.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

# app/api/v1/topics.py
from app.repositories.topic_repo import TopicRepository

@router.get("")
async def list_topics(db: AsyncSession = Depends(get_db)):
    repo = TopicRepository(db)
    items = await repo.list_ordered_by_best_score()
    return {"items": items}
```

## 迁移与高风险变更

数据库迁移属高风险操作，执行前先备份、出问题有回滚路径：

- **前置备份**：`cd backend && ./scripts/backup_db.sh`（SQLite 在线热备 / PG pg_dump，默认保留 7 份）。
- **回滚**：`cd backend && ./scripts/rollback_migration.sh [target]`。会先自动备份，再执行
  `alembic downgrade <target>`（`target` 可选，默认 `-1` 回退一格；也可传具体 revision 或 `base`）。
- **验证**：先在测试环境跑 `alembic downgrade -1`，确认上一版 schema 被恢复且应用能启动，再到生产执行。
- SQLite 缺大多数 ALTER 能力，迁移依赖 batch 模式重建表（见 `alembic/env.py` 的 `render_as_batch`），
  因此回滚前的备份尤为重要。
