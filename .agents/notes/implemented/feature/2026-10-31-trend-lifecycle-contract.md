# Agent Note: 趋势生命周期阶段标注合同

Status: implemented — #173 由竞品功能雷达候选池推进（Owner 指示），Worker 实施 + 独立 Verifier 两轮评审闭环

## Problem

热榜条目只有瞬时状态（up/down/new/stable），创作者无法判断「现在切入是早是晚」。Exploding Topics 的生命周期状态标签是同类验证过的形态（竞品雷达 2026-10-30 调研）。需要一个不落库、不改既有字段的读取时判定，且归一必须与跨平台共振聚类同口径，不能出现同一簇两条路径算出不同阶段的分叉。

## Decision

阶段是**派生值**：读取时在 service 层纯函数计算，不持久化、无迁移；`/api/v1/trending` 响应逐条新增 `stage` / `stage_reason`（可空），既有字段与排序一律不动；缓存随既有 `trending:list:` 载荷携带（含 scheduler 预热路径，两路载荷同形状）。前端 `/trending` 以 Badge 呈现：常青=teal、爆发=primary、回落=amber、发酵=neutral。

## 四阶段判定合同

互斥决策树，按序判定（`backend/app/services/trending_lifecycle.py`）：

1. **常青 evergreen**：窗口内不同日期在榜 ≥ `EVERGREEN_DAYS`(5)
2. **爆发 peaking**：在榜 <5 天且（最新排名较上一在榜日上升 ≥ `PEAK_RISE_RATIO`(0.30) 或排名 ≤ `PEAK_TOP_RANK`(10)）
3. **回落 declining**：最近一次名次转变下降（同日折叠后最少 2 个快照点）
4. **发酵 ferment**：其余（新上榜或中段）

窗口语义：`STAGE_WINDOW_DAYS = SNAPSHOT_RETENTION_DAYS`(7) 挂钩共享常量，cutoff 由 service 传入 repo（`list_snapshots_since`），恰含第 7 天当日。同日多平台快照折叠取最好名次；在榜天数按不同日期数累计（非连续）。阈值均为模块级常量，调参不改合同结构。

## 归一口径（不可分叉）

条目→快照标题的合并 =「精确同题 ∪ 相似度 ≥ `trending_cross.SIM_THRESHOLD`」，完全复用共振分析的关键词相似度（纯公共关键词得分，无公共词恒 0）。**禁止精确同题捷径旁路**——曾有实现让字面精确匹配的标题跳过相似扩展，同一共振簇算出两种阶段（peaking vs evergreen），已删并由 `test_exact_and_variant_titles_merge_into_same_cluster` 钉死；改归一时该测试必须保持绿。

## 容错

坏快照（形状非法）逐条 warning 跳过、逐标题计算异常降级 `stage=null`，GET /trending 不因坏数据 500（`test_trending_list_survives_corrupt_snapshot_rows`）。无窗口数据条目 stage 为 null，前端不渲染徽章。

## 边界与遗留

- 「常青」是 7 天窗口内语义，不是全生命周期常青；更长保留期后需重估
- stage 仅在缓存 MISS 路径计算（TTL 60s + 同步 30 分钟失效 + 启动预热），无 N+1（单条窗口批量查询）
- 排除信源（heiyan/ishugui）stage 恒 null；网文行不渲染徽章
