# Agent Note: 扩展模型吞吐与聚合管理先验证最小边界

Status: proposed — #151 从模型池与聚合流程旧路线图保留后续候选；不是当前实施进度

## Problem

多个 failover 候选不必然汇聚独立渠道吞吐；把分散的 LLM 阶段展示在管理台，也不等于需要引入通用工作流引擎。旧路线图同时混入未完成方案、旧 SQLite 约束与密钥运维事项。

## Decision

未来模型池切片先保留 [现有 LLM facade](../../../../backend/app/services/llm/__init__.py)，减少无效调用并测量队列等待、成功吞吐、429、成本与质量。独立渠道须确认真实配额归属，不能把多个 endpoint 当成互不共享限额。
配额预留/回收、deadline、取消后请求、任务租约与回写 fencing 属实际扩展时需要验证的合同；本篇不宣称已有 PoolDispatcher、TPM 预留、可恢复队列或多进程协调。

聚合管理候选按只读解释、隔离 dry-run、版本化发布逐步验证。若进入有限编排，只允许固定白名单节点与受控 DSL，不执行前端提交的任意代码；试跑不写正式结果，发布需明确回滚身份。

## Alternatives considered

- 首轮即引入 Kafka/微服务，或把一个调度器拆成许多浅模块：暂不采用，先证明当前瓶颈与独立测试面。
- 通过增 worker 绕过配额或省略共享状态协调：不采用，进程数不增加供应商配额。
- 从旧文恢复个人 BYOK：暂不采用。管理员系统模型已移除 owner/scope（b6a0037）；用户费用、内容可见性、凭据所有者和 quota_scope 隔离需单独决策。

## Consequences

仍需决定真实额度、失败分类、公平性/饥饿、报告容量保障及多进程协调方式。旧路线图的日期、P0 完成、剩余密钥轮换与灰度状态不作为现状。
当前调用和预算事实分别查 [call engine](../../../../backend/app/services/llm/_call_engine.py)、[预算保护](../../../../backend/app/services/llm/budget_guard.py)。本次只保存理由，未批准实施、数据库变更、运行成本或任意流程执行。
