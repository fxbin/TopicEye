# Agent Note: 清理 client 不能以缺失历史证明从未授权

Status: implemented — commit 2b6de2c507911339bab76e7bd10ebe929dc44ca8 / PR #148 已实现保护

## Problem

client 注册记录没有外键保护，既有 last_seen_at 又从未由业务更新；授权和 token 历史会定期清理。
因此“现在查不到历史”同时可能表示从未授权，或表示旧授权历史已被清除。直接据此删除会误伤正常注册；并发创建授权还可能产生缺失父 client 的子记录。

## Decision

持久保存首次清理边界，历史不明的旧注册保留。使用现有字段留下长期授权标记，并在清除旧子记录前转存仍可见的成功证据。
生命周期写入与清理共享 client 行锁，删除前重新核查资格；需要新快照的条件显式限定数据库隔离级别。
运行参数与实际步骤由本篇下方运行合同维护；原 docs 入口按所有者要求退役。

## Alternatives considered

- 仅查当前没有 token 就删除：否决，历史会消失，且授权可能正在进行。
- 只按年龄删除，或回拨启用边界清旧积压：否决，注册年龄不能证明从未授权。
- 为本次清理增加一套注册历史表或迁移：本次未采用，既有字段与持久边界足以实现保守保护。

## Consequences

部分历史不明的旧注册会长期保留，这是优先避免误删的明确代价。未来要处理这批积压，须另行取得可靠证据、备份和精确范围授权，不能通过扩大当前条件绕过。
回退代码能停止后续删除，不能重建已删注册；恢复依赖备份。笔记和本地测试不授权生产清理。

## Verification

[回归测试](../../../../backend/tests/test_mcp_oauth_client_cleanup.py) 覆盖资格边界、历史保护、并发双方胜出、回滚与作业状态。
授权创建与清理的共同父锁、成功标记先于历史删除，以及失败不误报 SUCCESS，均有对应回归；准确候选的结果见关联 PR，不把历史测试数量写成永久保证。

## 运行合同

### 清理资格与首次启用

现有每日 03:55 的 `cleanup_mcp_oauth` 作业同时处理过期授权、已撤销过期 token 和闲置 client。
首次成功运行在 `app_settings` 原子保存 `mcp_oauth_client_gc_started_at`；该时间只初始化一次，禁止回拨。

client 必须同时满足以下条件才进入删除批次：

- 注册时间不早于首次启用边界，且注册已超过 7 天（严格早于截止时刻）。
- `last_seen_at` 没有长期授权标记。
- 不存在任何授权或 token 行，包括尚未清掉的过期记录。

每批最多删除 500 条。首次运行不会批量清掉旧注册；启用后至少经过保留窗口，新闲置注册才可能被清理。
历史不明、早于启用边界的旧 client 保留。不能通过回拨边界来处理旧积压。

### 授权与并发保护

- 成功签发 token 时持久更新既有 `last_seen_at`；清理旧授权/token 前，先把现存成功证据转为此标记。
- 授权创建、授权码兑换与 refresh 兑换先锁 client，再修改子记录；已被清理的注册返回 SDK 的明确错误。
- 清理跳过被锁的 client，并在删除语句中再次核查资格。PostgreSQL 必须为 READ COMMITTED；其他隔离级别拒绝清理。
- client 删除、成功标记与历史清理共享调用者事务，出错回滚。损坏的启用时间显式报错。
- 调度追踪显示失败为 FAILED，成功摘要包含 clients、authorizations、tokens 的实际删除数。

参数与调用链入口：
[service](../../../../backend/app/services/mcp_oauth_service.py)、
[repository](../../../../backend/app/repositories/mcp_oauth_client_repo.py)、
[scheduler](../../../../backend/app/scheduler.py)。
回归见 [client 清理测试](../../../../backend/tests/test_mcp_oauth_client_cleanup.py)。

### 生产操作边界与回退

代码合并、本地并发测试和 CI 通过不代表生产首次启用、备份恢复或定时器已经验收。
生产首次启用前按 AGENTS 的高风险操作约定，确认准确候选、环境、PG 备份及恢复路径。
回退代码只能停止后续删除；已经删除的注册需依赖备份按原 client 身份与加密 secret 恢复。
本页不是立即执行生产清理的授权。

### MCP 工具范围

产品方向维持不新增显式业务写操作工具，范围与重开条件见
[只读工具范围决策](../scope/2026-10-24-mcp-tool-scope.md)。
这不等于所有读请求都没有持久化或费用：`get_daily_report` 未指定日期时，可能生成缺失日报并触发模型调用；以 AGENT_API 的接口说明为准。
