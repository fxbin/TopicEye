# Agent Note: LLM 调用记录的保留期合同

Status: implemented — #191（Owner 定 30 天），Worker 实施

## Problem

`llm_call_logs` 表**只增不减**：全仓没有任何删除路径，写入时也不裁剪，迁移里也没有分区/TTL。每次 LLM 调用插一行 27 列的记录（含 `error_message` 这个 Text 列 + 6 个索引）。

开发库实测 2026-11-01：17758 行、覆盖 6 周、表体积 10MB。按此量级一年约 15 万行、~90MB，生产用量只会更高。这不是"以后再说"的问题——它是一张没有上界的明细表。

## Decision

保留 **30 天**，每日 03:10 清理（`backend/app/scheduler.py` 的 `llm_call_log_cleanup`）。

### 为什么是 30 天（依赖逐个核对过）

保留期不是拍脑袋，要看**所有现存的消费方需要多久的历史**：

| 消费方 | 需要的历史 | 30 天够吗 |
|---|---|---|
| 预算熔断三窗保险丝 | **最长 24 小时**（`count_recent_llm_calls` 的 minute/hour/day 三窗） | 远超 |
| Prompt 管理页的调用量/成本统计 | 最近 7 天 | 够 |
| 成本审计 | 按月结算 | 够（覆盖一个完整月度周期） |

预算熔断是唯一会因删数据而**行为改变**的依赖——它读 `llm_call_logs` 里 DONE 调用的实际条数。它的最长窗口只有 24 小时，所以 30 天保留期删不到它要用的数据。**这条依赖是本次保留期的硬约束：保留期不得短于 24 小时。**

### 边界语义

删除条件是 `created_at < cutoff`，**正好等于保留期起点的那行保留**。与 `read_record`（180 天）、`metrics_snapshots`（7 天）、`web_vitals_samples`（30 天）的清理口径一致。

## 代码位置（各司其职）

- 常量 `LLM_CALL_LOG_RETENTION_DAYS = 30` → `app/services/llm_usage.py`（与其它几类保留期同一套做法：模块级常量，不进 config）
- 删除语句 → `app/repositories/llm_call_log_repo.py` 的 `delete_older_than`（SQL 归 repository）
- 编排 → `app/services/llm_usage.py` 的 `cleanup_old_call_logs`（算 cutoff、调 repo、记日志）
- 调度 → `app/scheduler.py` 的 `llm_call_log_cleanup`（每日 03:10，wrapper 负责 commit）

**无迁移**：不改表结构，只删数据。

## 明确不做

- 不改预算熔断的口径与窗口（删数据不影响它，见上）
- 不改表结构、不加分区（30 天 + 每日小批量删除，够用）
- 不做成本数据的归档/导出（将来若要长期审计再说）

## 遗留

- **单次删除量随用量增长**：当前一次删几千到几万行，PG 处理没问题，但会产生死元组交给 autovacuum。量级再涨一个数量级时可能要改成分批删除。
- **清理是纯 DELETE，没有归档**：超期数据直接消失，无法事后追查。如果将来要"超期仍可查"，得另加归档表或改成按月分表。
