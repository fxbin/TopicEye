# Agent Note: SelectBench 手动校准与导入合同

Status: implemented — #151 按所有者明确要求迁移既有入口；不改变运行或生产授权

## Problem

有限 feed、人工标注与导入权限必须区分；操作入口迁移不能把 unknown 当负例或把操作者声明当独立复核。

## Decision

本篇维护下列合同；修改对应行为时同步核对，参数与安全边界沿用迁移前原文。

本页维护离线工具的使用边界。它们是手动脚本，不接入定时任务；不凭有限精选 feed、来源标签或当前批次成绩宣称独立金标准确率。

| 入口（在 backend 目录使用 uv run python） | 用途与限制 |
|---|---|
| `scripts/selectbench_matrix.py` | 读取公开样本并构建对照矩阵；有限 feed 中没有出现的内容仍为 unknown，不是负样本 |
| `scripts/selectbench_sample.py` | 从矩阵及非 AIHOT 池抽样，去重、记录截断与实际数量；导出的 label/notes 留空待人工完成 |
| `scripts/selectbench_eval.py` | 在给定标注批次重放参数，记录配置/分析/标签快照；被引擎排除的正例仍进入召回分母，不当作独立留出验收 |
| `scripts/selectbench_import_labels.py` | 默认只验证 CSV；实际写入需显式 `--apply --reviewer-user-id <active-admin-id>` |

完整参数以各脚本 `--help` 为准。导入的操作者 ID 是声明，不是独立人工复核的证明。
导入在整批 ID、重复、标签、公开范围与 active-admin 校验后，用单事务记录人工来源及 CSV 摘要。
生产标注导入另按 AGENTS 的权限、备份和回滚约定执行；工具存在不等于已经授权写库。

代码入口在 [backend/scripts](../../../../backend/scripts)，回归见
[test_selectbench_tools.py](../../../../backend/tests/test_selectbench_tools.py)。

## Alternatives considered

只删除文档而保留断链或省略合同：不采用，入口收敛不能丢失使用边界。

## Consequences

本次未运行脚本、连接数据库或调用模型；已存在的脚本入口、默认只验证及显式写入边界保持不变。
