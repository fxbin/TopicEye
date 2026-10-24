# Agent Note: 趋势构成与来源线索保留不同时间语义

Status: implemented — 基线 738ac61 核实趋势成员和证据链；实现线索见 4414d6c、9af228c

## Problem

聚合计数和少量 top_items 无法还原完整历史成员；同一篇报道后来增加的来源线索，也不等于快照生成当时已经具备的证据。两者混在一起会制造可追溯或已核验的错觉。

## Decision

- 趋势成员由 [TopicTrendMember](../../../../backend/app/models/trend.py) 持久化，标题、原文、来源和时间依据由快照保存。成员与快照在业务事务中共同形成；兼容 top_items 只作为代表样本。
- [trends service](../../../../backend/app/services/trends.py) 明示 complete/sample_only/unavailable 等状态；缺失历史不从当前库反推并冒称完整。公开快照及成员读取受公共可见性限制。
- [来源证据](../../../../backend/app/services/evidence_service.py) 为平台无关线索，复用同一事件事实。多个独立来源、官方一手链接与“事实已被核验”不是等价关系；当前线索不能冒充历史冻结状态。

## Alternatives considered

- 用历史 Top 链接回填全体成员：不采用，少量样本不足以重建分母。
- 只给 X 打“可信”标记，或用转载数量直接提高真实性：不采用，平台、独立发布者和上游转载需区分。
- 为展示来源信息重建第二套事件归并真源：不采用，事件读取与启用合同沿用 [content-event-coverage](../feature/2026-10-24-content-event-contract.md)。

## Consequences

冻结成员增加存储与写入成本，当前来源线索会随内容变化；历史证据版本化与私有趋势扩展须另立范围。
回归入口 [test_trend_traceability.py](../../../../backend/tests/test_trend_traceability.py) 已存在；本次只核对合同与源码，不重跑数据库、迁移或真实样本验收。
