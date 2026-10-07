# Agent Guidelines

## 一、这个仓库是什么

TopicEye 是给内容创作者用的选题雷达：持续抓取 25+ 信源（RSS / Reddit / YouTube /
播客 / newsletter / 趋势榜），用可解释的六维引擎给每条内容打分，挑出今天值得写的题目。

两件不看代码就会踩空的事：

- **两套存储分工明确**：Postgres 存事务数据（content / user / auth，见
  `app/repositories/`）；DuckDB 承担分析查询（picks / stats / topics / reports，见
  `app/services/duckdb_service.py` 及其 mixin）。跨层读写时先确认自己在哪一套里。
- **缺陷状态看 GitHub**（`gh issue view <n> --json state,closedAt`），根因判定见
  [`.agents/notes/`](.agents/notes/)，跑测守则见第三节。

**AGENTS.md 即模型接口**：本文件喂给 agent，命令、路径、门禁清单过期等于静默的错误。遇到
文中描述与代码不符时以代码为准并顺手修正本文件；承载行为变更的 PR 必须同步核对相关段落。
本文只写本仓库特有的事实与约束，与通用 skill 规则冲突时以本文为准。

## 二、动手前：权限与不可违背的约定

每个 agent 会话开场即生效的**三句权限档位**（任何一条要突破都必须先获所有者批准）：

1. **可写范围**：仅本仓库工作区（分支、暂存、本地提交）；仓库外文件一律只读。
2. **提交与远端写入**：`git commit`、push 分支、创建 PR 属常规动作；**合并 PR、直推 main、force-push、删除提交/历史改写——逐次审批**（见 4.1）。
3. **高风险操作**：数据库迁移、删除类命令、依赖大版本升级——先备份、留回滚路径，再动手（见 2.3）。

### 2.1 安全不变量

skill 的通用机制不覆盖以下四条：

- **教训必须机器化**：事故/缺陷的复盘结论只有落成测试或 CI 门禁才算关闭，只写进文档不算（现状范例：`backend-layering` 与 `agent-docs` 两个作业，以及每条缺陷配套的回归测试）。
- **中断重试纪律**：被中断的副作用操作（迁移、远端写入、发布）不得盲目重试——先核实外部状态（迁移版本、远端 ref、受影响数据行）或问所有者；仅只读/幂等操作可直接重试。
- **安全关键依赖的采用度门槛**：承担安全不变量的依赖（加密、认证协议、沙箱类）必须有被证明的采用度与维护活跃度；其余位置优先选成熟依赖而非手写。
- **禁止安静的失败**：启动期任何组件「挂起等待/未挂载/被跳过」必须显式报错或记 warning；静默 PENDING 按缺陷处理（先例：健康与生命周期加固波，#71~#73）。

### 2.2 后端分层

依赖方向严格单向，禁止逆向或跨层：

```text
api/v1/ ──► services/ ──► repositories/ ──► models/ ──► sqlalchemy
```

| 层 | 允许 | 禁止 |
|---|---|---|
| `api/v1/` | 路由声明、请求校验、调用 service / repository、response shaping | `import sqlalchemy`；`from app.models import <ORMModel>`；直接 `select(...)` / `db.execute(...)` / `db.add(...)` |
| `services/` | 业务编排、事务边界、调用 repository、跨 repo 组合 | 无（允许直接 import sqlalchemy / app.models） |
| `repositories/` | ORM 唯一入口，CRUD + 复杂查询封装，继承 `BaseRepository[ModelType]` 或独立类 | 互相 `import`（repo 之间不依赖）；写业务逻辑（业务逻辑属于 service） |
| `models/` | 纯 ORM 声明、字段定义、`__table_args__` | 业务方法、副作用、IO 操作 |
| `schemas/` | Pydantic 请求/响应模型、序列化 | ORM import、DB 访问 |

**例外**（允许 api 层 import，因为它们是值对象或依赖注入需要，不是 ORM 模型）：
`app.models.<X>` 中的 Enum 类、`AsyncSession` 类型注解、`app.core.database.get_db`、
`IntegrityError` 等异常类。

**机器强制的边界**：`make layering`（等价于 `cd backend && uv run python
scripts/check_layering.py`，CI 作业 `backend-layering`）只作用于 `app/api/v1/`，且只认两条：
禁止 `import sqlalchemy`（`sqlalchemy.ext.asyncio` / `sqlalchemy.exc` 除外），禁止直接写
`select/insert/update/delete` 构造与 `db.execute/db.add/db.scalars/db.scalar`。上表其余禁止项
它查不出——`from app.models import <ORMModel>` 与 api 层合法要用的 Enum、依赖注入同模块，
自动判定会误报，只能人工看。

### 2.3 迁移与高风险变更

- **前置备份**：`cd backend && ./scripts/backup_db.sh`（PG pg_dump，默认保留 7 份）。
- **回滚**：`cd backend && ./scripts/rollback_migration.sh [target]`。会先自动备份，再执行 `alembic downgrade <target>`（`target` 可选，默认 `-1` 回退一格；也可传具体 revision 或 `base`）。
- **验证**：先在测试环境跑 `alembic downgrade -1`，确认上一版 schema 被恢复且应用能启动，再到生产执行。
- `alembic/env.py` 的 `render_as_batch=True` 对 PostgreSQL 无害，保留 batch 模式备用。

## 三、怎么验

### 3.1 跑测试前必读

`backend/tests/conftest.py` 有 autouse `clean_tables` fixture，会对 `DATABASE_URL`
指向的库执行 `TRUNCATE ... CASCADE` 并终止其它连接。**直接对开发库跑 `pytest tests/`
会清空数据。**

| 场景 | 命令 |
|---|---|
| 后端全量（推荐） | `make test-backend` —— 自动起一次性 PG 容器（127.0.0.1:5433），跑完即删；`TEST_PG_PORT` 可换端口并行 |
| 针对性 PG 测试 | 自建一次性库（`CREATE DATABASE ..._tmp`），`DATABASE_URL` 指向运行，用完 `DROP DATABASE` |
| OAuth 隔离测试 | `DATABASE_URL='postgresql+asyncpg://dummy:dummy@localhost:5432/never_connect' uv run --no-sync python -m pytest tests_oauth_patch/` —— 全 mock 不连库；**必须 `python -m`**（该目录无 `__init__.py`，裸 `pytest` 解析不到 `app` 包） |

### 3.2 改了什么，就验什么

```bash
git log --name-only -5 -- <改动的文件>   # 历史上和它一起改过的测试
make test-backend                         # 或直接跑全量
```

挑着跑时盯住改动有没有跨到存储分工上——读写落在 Postgres 还是 DuckDB，跨错了口径会静默不一致。

### 3.3 其它命令

- Backend Python syntax: `cd backend && uv run python -m py_compile <changed-python-files>`
- Backend tests: `cd backend && uv run python -m pytest <relevant-tests> -q` —— `-k` 是 pytest 的**全局**过滤器，`pytest a.py b.py -k x` 会同时筛两个文件，不限于 a.py；要只筛某个文件就分开跑（依赖由 uv 管理：`uv sync` 安装，事实源为 pyproject.toml + uv.lock）
- Shell scripts: `bash -n <script>`
- Layering: `make layering`
- AGENTS.md 引用: `cd backend && uv run python scripts/check_agent_docs.py`（校验本文引用的路径与 make 目标，CI 作业 `agent-docs`）
- Frontend type check: `cd frontend && npx tsc --noEmit`
- Frontend tests: `cd frontend && npm run test:coverage`（含覆盖率门禁，对应 CI `frontend-tests`）
- Full quality gate: `make lint`（ruff + 分层检查 + 前端类型检查）

## 四、怎么交

正常路径：**有意义的变更必须有 issue → 分支 → PR → 检查绿 → 合并**，直推 main 不是常规路径。

### 4.1 审批闸门（所有者定）

逐次审批的那一类（第二节第 2 条），一次授权不覆盖下一次。其余属常规动作，默认行为是
实现并本地验证 → 报告变更摘要/diff → 等批准再 commit。**所有者也可在任务开始时一次性授权
本次范围内自行 commit 与建 PR**，agent 据此连做多个切片（每个切片仍是独立 commit，见 4.3），
结束时报告完整 diff，形状不合意 `git reset` 回退即可。

- **分支命名**：`issue-<number>-<short-slug>`（如 `issue-90-llm-fallback-requeue`）。
- **热修例外**：生产事故可直推 main 修复，但须在 24h 内补 PR 或在关联 issue 留 post-hoc 审计评论（原因、影响面、回归验证）。
- main 的 push CI 自动复验由 PR #65 引入；DoD 证据以 main 运行为准。

### 4.2 提交信息

形如 `<type>(<scope>): <中文说明>`，`type` 用 `fix` / `feat` / `chore` / `test` / `docs`，
`<scope>` 用这次实际碰到的模块名（`auth`、`scoring`、`trending` 等），不套固定清单。

```text
fix(auth): 降低登录链路数据库写锁等待
fix(trending): 合并重复信源筛选项
test(scoring): 补推荐档位边界的断言
docs: 跑测前必读补上 OAuth 隔离测试为什么必须 python -m
```

**说明用日常中文**，不搞翻译腔、不生造术语、不为强调堆砌修饰。读者应能从一句话
看出仓库变成了什么样，而不是读到「登记 X」「同步 Y」这类流程动作。

末尾的 `(#NN)` **只写 issue 号**——GitHub 两者共用编号空间，写错不报错，只让读的人分不清
是哪种对象；分支与 issue 的对应关系写在 PR 描述里。编号不是必写，只有它确实是这次改动的
原因时才写，且不追溯既往提交。

### 4.3 commit 边界

- 一个 commit 只做一件事：不要把 backend / frontend / docs / config 混在一起（除非
  同一修复必需），测试与它验证的代码同 commit。
- 本地文件不进库：`backend/.env`、数据库、venv、缓存、截图、生成的浏览器产物。
- 显式暂存路径，工作区有他人改动时禁 `git add -A`。

改写历史前建备份分支（`git branch backup/<理由>-<日期> HEAD`），改完用
`git diff <备份分支>..HEAD` 验证文件树未变——空 diff 说明只改了历史没改内容。本仓库**一律
禁止 force-push main**（不只是需审批）；其他分支的 force-push 按第二节第 2 条逐次过闸，
历史改写只存在于本地。

> 暂存范围、提交形状、产物边界由 skill 的 `git_workflow_guardrail.py`（G0–G4 阶段）
> 机器校验，本节只管机器判不了的「这算不算一件事」。

### 4.4 Verifier 契约

CI 六项检查（types / tests / lint / layering / agent-docs / security-scan）是机器
Verifier，全绿是合并前提；预存红必须显式处置并留记录。PR 描述须附 Worker 证据（本地
验证命令 + 结果，见 PR 模板 Verification 段）。承载行为变更的 PR 还需在模板 Verifier
verdict 段落记录独立复核结论（复核者不得是同一实现过程）。

- **当前 `security-scan` 为红**：唯一来源是前端 npm audit 的 8 个 high，全在 eslint
  工具链（`eslint-config-next` → `@next/eslint-plugin-next` → `fast-glob` →
  `micromatch` → `braces`）。`npm audit fix --force` 的方案是降级到
  `eslint-config-next@14.2.35`（破坏性变更），未采用。合并前显式声明这是已知预存红，不要
  误记成自己引入的失败。依据见
  [`.agents/notes/rejected/`](.agents/notes/rejected/2026-09-28-npm-audit-force-downgrades-eslint-stack.md)。
  后端 pip-audit 曾因 `multidict 6.9.0`（GHSA-54p9-h82j-f925，aiohttp 传递依赖）转红，
  已随 #99 升到 6.9.1 修复——后端再红即新问题，不要归并到这条预存红。
