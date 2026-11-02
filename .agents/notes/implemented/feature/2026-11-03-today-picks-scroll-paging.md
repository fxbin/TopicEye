# Agent Note: 今日选题滚动加载的分页口径

Status: implemented — #218，Worker 实施

## Problem

今日选题页 `/today-picks` 原来的「加载更多」按钮是**按累计条数重选**，不是**按页追加**：

- 前端把 `limit` 从 40 逐步放大（40 → 80 → 120 → 200），每次整表重新请求、整表替换。
- 每批都重传全量：第 4 次点击传 160 条完整卡片载荷，而不是新增的 40 条。
- 后端 `limit` 上限 200（`contents.py` 的 `le=200`），所以最多点 4 次，第 5 次必然 422——
  越往后越加载不动。
- 交互割裂：必须主动点按钮才能看到后续内容。

## Decision

改成**后端真分页 + 滚动自动加载**：`GET /contents/today-picks` 增加 `offset` 参数，
前端用 `IntersectionObserver` 在滚动到底时自动接下一批，按钮保留作兜底
（触屏 / 无障碍 / 自动加载失败时仍可手动展开）。

### 为什么不能用「拉大 limit」当追加

这是本次最关键的一条：**当日精选的选池本身依赖 `limit`**。

`_select_personalized_slate(scored_rows, boosts, limit)` 里，探索位与个人位按 limit 的
比例分配（`explore_slots = min(limit-1, round(limit*0.2))`），个人位取
`limit - explore_slots` 条。limit 一变，选出来的**集合和顺序都会变**。

用 30 组随机 boosts / 评分实测 `limit=40 → 80 → 120`：

- 集合单调增（不会丢条目）✔
- 已显示条目的相对顺序保持 ✔
- **但不是严格前缀** ✘ —— 新条目会插到中间位置。

也就是说，拉大 limit 实为**重选**：用户点一次按钮，已经看过的卡片会被重新洗牌。
这既不是追加，也就谈不上增量加载。

### 选池改为按页推进

`_select_personalized_slate` 改成**逐页推进**：个人位与探索位各自从各自的序里往后取，
已发出的条目不再进入后续页。这样同一入选池 + 同一 limit 下，第 k 页一定是第 1 页的
**稳定延续**——追加后续页不会重排已展示的条目，也不会重复或漏项。`offset` 只做切片，
不参与选池。

无 boost（匿名 / 无兴趣向量）时走基础序切片，行为与旧实现完全一致。

## 三条边界

### 1. 缓存键必须含 offset

`TodayPicksCacheParams` 加了 `offset` 字段并进 key。否则第 2 页会命中第 1 页的缓存，
把首屏内容重复发出去——这是会直接表现为「加载更多但内容不变」的错误。

缓存命名空间同步从 v6 提到 v7：响应新增了 `offset` / `has_more`，`page` / `page_size`
从写死的假值改成如实反映窗口，v6 的旧载荷对新前端是误导。

### 2. `total` 不随 limit / offset 变化

侧边栏徽标 `today_count` 只为拿 `total`（用 `limit=1` 调一次）。`total` 必须恒等于
入选池总数，否则分页参数会把徽标数带偏。回归测试锁住这一点。

### 3. 前端合并按 id 去重

翻页窗口内可能有新内容入库导致 offset 位移，后一页会重复出现上一页已加载的条目。
前端用 `mergePickPage` 按 id 去重后再追加（与首页 `mergeItemsById` 同一口径）。
下一批的 `offset` 用**实际已加载条数**而不是已请求条数，这样位移造成的缺口能被补回。

## 本页滚动容器的坑

今日选题页的滚动容器**不是 window**。`ClientLayout.tsx` 里是
`<div className="min-h-0 flex-1 overflow-auto">`，根节点 `h-dvh overflow-hidden`，
window 根本不滚动（实测 `HTML.scrollHeight === clientHeight === 900`）。

所以滚动加载必须用 `IntersectionObserver`，不能用 window scroll 事件——scroll 事件不
冒泡到 window，监听 window 收不到。同 `admin/settings` 的既有做法。

## Alternatives considered

- **保留「拉大 limit」，只在前端按 id 去重**：能消除重复卡片，但已看条目仍会被重新洗牌，
  且每批重传全量、200 条天花板依旧。不解决根本问题。
- **给今日选题也绑浏览快照（首页那套 `feed_snapshot` + 409）**：首页需要是因为它的
  折叠事件顺序会随归并纠错变化。today-picks 不走事件折叠快照，且本次目标是滚动加载，
  引入快照会让「顺序变了就 409、要求刷新列表」变成常态体验。先不做；真出现顺序漂移
  问题再评估。
- **纯滚动加载、去掉按钮**：触屏与无障碍场景失去手动展开的入口。保留按钮兜底。

## Consequences

- 今日选题与首页的加载策略一致了：都是真分页 + 按 id 去重追加。
- 后端每批只返回新增条目，传输量随批次线性增长而不是平方增长。
- 200 条天花板解除。
- 本地库的分数在 percentile 门槛下可能全被筛掉（`selected` 全为 false），此时
  today-picks 返回 0 条属既有环境状态，不是本次改动引入的。

## 回归入口

```bash
cd backend && .venv/bin/python -m pytest tests/test_today_picks.py -q
cd frontend && npx vitest run src/app/today-picks/_paging.test.ts
```
