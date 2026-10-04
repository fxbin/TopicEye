# Agent Note: LLM 降级兜底应写 NULL 分数，而不是写死常数

Status: proposed — 已定位，未实现；AGENTS.md 暂不承载此告警，等实现后再决定

## Problem

`app/services/analysis.py:_local_analysis_result` 在 LLM 熔断打开、请求被拒、预算超限，
或返回结果不合契约时启用。它产出**写死的六个常数**：

```python
quality_score   = 62 if has_content else 48
hot_score       = 68 if is_trend_source else 55
creator_score   = 64 if has_content else 50
viral_score     = 58 if is_trend_source else 50
freshness_score = 70
risk_score      = 28
```

`has_content` 只看正文是否 ≥80 字，`is_trend_source` 只看信源名是否含 hot/trend/reddit
等词。**与文章写了什么无关。** 加权后 `curation_score` 收敛在 61.0–64.3。

后果：几百条降级内容的分数几乎相同，混在真实内容里参与 Today Picks 排序，代表不了内容质量。

## 关键发现：下游早就按 NULL 过滤了

分数列本身可空（`app/models/analysis.py:38`，`Mapped[float | None]`），且四条消费路径
**全部**已经写好 `curation_score IS NOT NULL`：

| 消费方 | 位置 |
|---|---|
| DuckDB picks（主路径） | `_duckdb_picks_mixin.py:111` |
| DuckDB reports | `_duckdb_reports_mixin.py:35, 94` |
| DuckDB stats | `_duckdb_stats_mixin.py:84`（`:153` 的 analyzed 计数同样只算非 NULL） |
| OLTP picks 回退 | `today_picks.py:311` `if latest.curation_score is None: continue` |

也就是说「NULL = 没有分数 = 不合格」这套约定在消费层是完整的，**只有兜底路径没走进去**。
`scoring_engine.py:453` 还得专门把 `local_fallback` 从 P70 百分位门槛里排出去，
正是这个漏洞的补丁。

## Proposal

`fallback_used=True` 时，`curation_score` 与六个维度分数一律写 **NULL**；摘要、标签、
建议照写（内容本身仍可用，只是不给它打分）。下游零改动，四条 `IS NOT NULL` 自动排除。

配套删除 `scoring_engine.py:449-459` 里的 P70 排除与「全候选皆降级时改用全量分数」
兜底——前者变冗余，后者变不可达。

### 必须避开的坑

`app/services/analysis_normalize.py`：

- `:153` `_clamp_score(scores.get(key), 50)` —— 缺失的分数填 **50**
- `:159` `_clamp_score(curation.get("curation_score"), 0)` —— 填 **0**

而兜底结果在 `analysis.py` 的两个分支里都会被 normalize（`if not fallback_used` 的
`else` 分支，以及契约校验失败的重置分支）。**直接让 `_local_analysis_result` 返回
None 会被填成 50 和 0**——50 比多数真实分还高，`IS NOT NULL` 也拦不住。

改点应在 `_build_analysis_record` 入口按 `fallback_used` 短路，同时给
`_apply_cross_market_bonus` 加 None 保护（它当前直接吃 `curation_score` 数值）。

## Alternatives considered

- **引入独立 `ContentStatus.DEGRADED`。** 否决：要迁移，且每个消费端都得再加一道状态过滤。
  NULL 分数已经把「不合格」表达完整了，加状态是重复表达。
- **消费端一律加 `summary_source` 过滤。** 否决：这就是当前的补丁方式，
  `scoring_engine` 加了、picks 没加，迟早再漏一次。NULL 是数据自带的语义，不依赖每个
  消费方记得加条件。
- **熔断/预算错误改走 ERROR 路径。** 暂不采纳，范围更大。见下。

## 更深一层（本次不做）

`analysis.py:508` 的注释说明了当初为何不用 ERROR 路径：熔断与预算熔断可能持续一整天，
走 ERROR 会消耗 `analysis_attempts`，整批 backlog 会在一次长故障里烧光重试预算、
全变永久 ERROR。

治本方向是把「LLM 不可用」与「这条内容分析失败」解耦——前者不消耗 attempts，只设长
cooldown。做完这步，降级内容可以回到统一的重试语义，`#90` 那套独立 requeue 路径
（`analysis_requeue.py`）也能并入 ERROR 重试。**与数据质量是两件事，先做 NULL 止血。**

## Consequences

- 熔断期间 Today Picks / 日报会变空。这是诚实信号（「今天没有够格的内容」），
  替代当前「塞一批 61-64 假分、让人以为选过了」。**属产品决策，需所有者确认。**
- 降级内容仍在库、仍在内容列表可见，只是不进 picks / stats / reports。
- `#90` 回收路径不受影响：它按 `summary_source == "local_fallback"` 判定，与分数无关。
- 「本地速览」前端标记在 picks 里将基本失效，需另行确认该标记的其它用途。

## 验收

- 回归测试断言「兜底分析不产生任何分数」（六维 + `curation_score` 全为 NULL）
- 回归测试断言「真实 LLM 分析的分数不受影响」
- 四条消费路径各有一条「NULL 分数被排除」的断言
- 现有 `test_analysis_requeue.py` / `test_scoring_*` 全绿（回收与打分语义未变）
