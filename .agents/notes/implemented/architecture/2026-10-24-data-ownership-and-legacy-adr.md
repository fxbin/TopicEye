# Agent Note: 数据归属模型与数据库后端分开判断

Status: implemented — 基线 738ac61 核实当前代码；#151 补录历史 ADR 的适用边界

## Problem

旧 ADR 同时承载公共/私有内容模型、SQLite/PG 双后端和个人模型配置。它们演进速度不同；把整篇 Accepted 当成当前合同，会重新引入已移除的 SQLite 和模型 BYOK 假设。

## Decision

2026-06-14 的 ADR 原稿已完整归入本地备份，原 docs 入口按所有者要求退役。本篇维护仍有效的归属选择及已被代码取代的假设：

- 公共池与用户私有层继续分开：owner_user_id 为 NULL 表示公共，非空表示用户私有；可见范围是公共内容加该用户的私有内容。共享资源由管理员维护，不能因此推导完整租户隔离。source/content/report 的 owner 不能由聚合结果或界面路径推断，查询与投递出口均需实施可见性限制。
- 当前 OLTP 仅支持 PostgreSQL；DuckDB 承担分析读取。双后端保留条款已由 `1809efd` 的移除实现取代。
- `llm_models` 的 owner/scope 已由 `b6a0037` 删除；不能继续把它当作用户私有资源的照抄模板。恢复 BYOK 须另立产品和凭据/配额隔离方案。

## Alternatives considered

- 整篇旧 ADR 原样提升为当前指令：不采用，保留历史并不代表恢复已退场能力。
- 以换数据库实现完整租户隔离：不采用，存储引擎和 owner 查询约束是两个问题。

## Consequences

未来变更通过新决策交叉引用本篇，不改写原始理由；早期 ADR 的原始措辞仅用于历史恢复。公共/私有的日报细节沿用 [日报 owning note](../bug-fix/2026-10-22-daily-report-ownership-and-generation.md)。
当前事实入口为 [数据库 profile](../../../../backend/app/core/db_backend.py)、[内容模型](../../../../backend/app/models/content.py)、[日报模型](../../../../backend/app/models/daily_report.py)；源码存在不等于本次重跑隔离或生产验收。
