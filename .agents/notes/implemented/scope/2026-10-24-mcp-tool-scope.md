# Agent Note: MCP 写工具与 OAuth 运维清理分开立项

Status: implemented — 所有者确认不规划显式业务写工具，#118 按 not planned 关闭；client 清理另以 #147 实现

## Problem

完整 scope、授权码重放连坐与 client 垃圾清理原先放在同一个待办中，触发条件却不同。继续捆绑会让独立的运维卫生依赖未立项的产品方向，也容易把关闭待办误解为安全清单已实现。

## Decision

- 维持现有工具方向，不立项新的显式业务写操作工具。权限模型、resource 双路径和重放连坐的原前置清单保留在 [#118](https://github.com/fxbin/TopicEye/issues/118)。
- client 清理独立立项，按其生命周期、数据保护与备份边界验收，不重新开启整套写工具改造。
- “只读工具方向”不表示零副作用：缺失日报生成等行为与费用以 [AGENT_API.md](../../../../AGENT_API.md) 为准；OAuth 注册、授权与运维写入也不在这句范围声明中取消。

## Alternatives considered

- 把所有内容都随 #118 关闭并当作已解决：否决，关闭产品待办不能伪造实现状态。
- 先做完整写权限模型，再做 client 清理：否决，当前没有显式写工具立项，依赖不成立。

## Consequences

未来决定立项显式业务写工具时，重开 #118 并完成权限前置验收。现有 scope 工具登记与缺省拒绝闸门继续有效。
当前 issue 状态由 GitHub 维护，本笔记只保留分流理由。client 清理的实现依据为 commit `2b6de2c507911339bab76e7bd10ebe929dc44ca8` / [PR #148](https://github.com/fxbin/TopicEye/pull/148)。
