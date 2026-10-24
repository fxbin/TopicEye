# Agent Note: 共享组件按语义收敛，保留有理由的差异

Status: implemented — 基线 738ac61 核实现有组件和注释；#151 从旧重构计划提炼

## Problem

旧前后端审核与重构计划混合了真实重复、过期缺陷清单和外观相近但职责不同的组件。逐项追求“重复清零”会让调用方为一个通用接口增加无意义适配。

## Decision

共享色彩、反馈分类和导航等同口径内容由共同模块维护；抽取组件前先比较输入语义、交互、空值与错误状态。
[SourceForm](../../../../frontend/src/components/SourceForm.tsx) 的分类不含“全部”，因为它写入单个信源；[design-tokens](../../../../frontend/src/lib/design-tokens.ts) 的筛选分类允许“全部”。
[趋势页](../../../../frontend/src/app/trends/page.tsx) 的简单折线与 [公共 Sparkline](../../../../frontend/src/components/Sparkline.tsx) 的富信息趋势卡保留不同接口，当前注释明确记录不合并理由。

## Alternatives considered

- 所有同名组件、分类数组强行统一：不采用，展示筛选值不能成为持久化分类，简单折线也无需承接富卡片全部参数。
- 为消除文档中的重复而重构代码：不采用；先证明真实调用契约一致。

## Consequences

同口径重复仍需消除，例如 [反馈标签](../../../../frontend/src/lib/product-feedback-labels.ts) 和 [管理导航](../../../../frontend/src/lib/admin-nav.ts)。本笔记不证明旧计划的所有切片已经完成，也不重立过期的切片清单、tag 或验收数量。
本轮未修改 UI；未来抽取仍需相关交互与视觉验证，类型通过不能单独证明行为无变化。
