# Agent Note: 统一评分口径与证明推荐效果是两件事

Status: implemented — 既有口径门禁见 fc26985；#151 整理 AIHOT/Easel 研究的复用边界

## Problem

旧 AIHOT 对标、Easel 调研和早期 PRD 包含隐含权重猜测、榜单样本统计与大量候选功能。公开精选池不等于全量候选，角色讨论的 adopt/trial 也不是已完成的产品验证。

## Decision

- 内部评分权重、门槛与术语从 [scoring_caliber](../../../../backend/app/core/scoring_caliber.py) 取用，前端镜像通过 [检查脚本](../../../../backend/scripts/check_scoring_mirror.py) 对账；不把外部产品的隐含规则抄成事实。
- 候选资格、事件展示代表、价值判断与页面容量分别解释。某条未展示不自动等于负样本；按批次分位数入选也不等于经过校准的正确概率。
- 历史有限 feed、合成回归与模拟圆桌只提供研究线索。真实效果需独立标注、分离校准/留出，并比较实际调用链；具体离线合同沿用 [SelectBench](../verification/2026-10-24-selectbench-contract.md)，事件试点沿用 [既有验证 note](../../proposed/verification/2026-10-24-event-normalization-real-evidence.md)。

## Alternatives considered

- 从公开分数反推竞争产品的隐藏轴、精确权重或人工编辑参与度：不采用，证据不可识别。
- 把多个榜同时出现直接当事实核验，把 LLM 爆文潜力分当实测传播率：不采用，指标来源不同。
- 据旧 PRD 恢复“低粉爆文”承诺：不采用。历史退场见 `32194b4`；重开需先证明粉丝、阅读与互动等输入的覆盖及口径，不能由主观分补足缺失事实。

## Consequences

口径检查保护内部一致性，不保证模型判断质量或用户采用。旧研究提出的行为锚点、显式画像、支柱配额、供给缺口和第三方备源属于各自待验证假设；本次整理没有批准其上线、固定探索比例或把外部 API 纳入 SLA。
重开应绑定真实来源、分布变化、误杀/降级语义和可回收条件，而不是沿用旧研究的共识票数、日期或测量结果。
