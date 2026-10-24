# MCP OAuth 与 client 清理运维

本页维护 client 清理的当前运行合同。MCP 接口、认证配置与已知副作用见
[AGENT_API.md](../AGENT_API.md)；取舍理由见
[历史不明注册的保护决策](../.agents/notes/implemented/architecture/2026-10-24-mcp-client-gc-history.md)。
修改行为或参数时同步本页，不把这些细节重新堆进 AGENTS。

## 清理资格与首次启用

现有每日 03:55 的 `cleanup_mcp_oauth` 作业同时处理过期授权、已撤销过期 token 和闲置 client。
首次成功运行在 `app_settings` 原子保存 `mcp_oauth_client_gc_started_at`；该时间只初始化一次，禁止回拨。

client 必须同时满足以下条件才进入删除批次：

- 注册时间不早于首次启用边界，且注册已超过 7 天（严格早于截止时刻）。
- `last_seen_at` 没有长期授权标记。
- 不存在任何授权或 token 行，包括尚未清掉的过期记录。

每批最多删除 500 条。首次运行不会批量清掉旧注册；启用后至少经过保留窗口，新闲置注册才可能被清理。
历史不明、早于启用边界的旧 client 保留。不能通过回拨边界来处理旧积压。

## 授权与并发保护

- 成功签发 token 时持久更新既有 `last_seen_at`；清理旧授权/token 前，先把现存成功证据转为此标记。
- 授权创建、授权码兑换与 refresh 兑换先锁 client，再修改子记录；已被清理的注册返回 SDK 的明确错误。
- 清理跳过被锁的 client，并在删除语句中再次核查资格。PostgreSQL 必须为 READ COMMITTED；其他隔离级别拒绝清理。
- client 删除、成功标记与历史清理共享调用者事务，出错回滚。损坏的启用时间显式报错。
- 调度追踪显示失败为 FAILED，成功摘要包含 clients、authorizations、tokens 的实际删除数。

参数与调用链入口：
[service](../backend/app/services/mcp_oauth_service.py)、
[repository](../backend/app/repositories/mcp_oauth_client_repo.py)、
[scheduler](../backend/app/scheduler.py)。
回归见 [client 清理测试](../backend/tests/test_mcp_oauth_client_cleanup.py)。

## 生产操作边界与回退

代码合并、本地并发测试和 CI 通过不代表生产首次启用、备份恢复或定时器已经验收。
生产首次启用前按 AGENTS 的高风险操作约定，确认准确候选、环境、PG 备份及恢复路径。
回退代码只能停止后续删除；已经删除的注册需依赖备份按原 client 身份与加密 secret 恢复。
本页不是立即执行生产清理的授权。

## MCP 工具范围

产品方向维持不新增显式业务写操作工具，范围与重开条件见
[只读工具范围决策](../.agents/notes/implemented/scope/2026-10-24-mcp-tool-scope.md)。
这不等于所有读请求都没有持久化或费用：`get_daily_report` 未指定日期时，可能生成缺失日报并触发模型调用；以 AGENT_API 的接口说明为准。
