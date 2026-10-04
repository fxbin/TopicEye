# Agent Note: 生命周期加固波的核心判定——后台任务必须被注册，停机必须可回收

Status: implemented — 已随 PR #74~#78 落地，测试与代码注释均已固化

## Problem

2026-09-27 的 #6 审计一波查出三个 P0/P1 缺陷，表面症状各不相同（健康端点恒返回 ready、后台任务静默丢异常、停机挂死），但根子是同一个认知缺口：**这个仓库里「谁负责什么」从来没有被写下来过**。

同类问题在管理后台重演了一次：#88 查出概览卡片 13 张、面包屑 10 条、侧边栏 15 项三份目录互相矛盾——分类同样没被写下来过，于是三处各写各的。

## Decision

三条判定同时生效：

1. **无主的后台任务视为缺陷。** 任何 `create_task` 必须登记进 `app/core/task_registry.py`（`track_background_task`），否则视为缺陷而非风格问题。
2. **启动期的静默按缺陷处理。** 组件「挂起等待 / 未挂载 / 被跳过」必须显式报错或记 warning；`except: pass` 一律改成 `logger.exception` 留痕。
3. **凡是「分类」被复制到多处的地方，必须抽成单一事实源。** #88 的修复不是补齐 4 条映射，而是合并到 `frontend/src/lib/admin-nav.ts`，由清单派生映射。

## Alternatives considered

- **在文档里写清楚有哪些后台任务。** 否决：会随代码增减而腐烂。改成机器可查的注册表 + 生命周期测试，文档只留入口。
- **给停机链加一个总 deadline 就够了。** 否决：`jieba` 预热的 `to_thread` 不可取消，deadline 到点只能强杀进程，留不下清理痕迹。改为逐项收编（`_shutdown_prewarm_tasks`）+ 每项独立超时。
- **把健康检查的 OLTP 判定改成真探测就完事。** 否决：真正的坑是 DuckDB 有 fallback、scheduler 可被配置禁用，这两种是**受支持的部署形态**。判定必须按「OLTP 可达即 ready」写死，并把这个前提写进注释，否则下一个人会试图"修"掉它。

## Consequences

- 每条根因判定都留在了代码注释里（如 `daily_reports.py:286` 记着 `issue #72` 的 `except: pass` 前史），不依赖本笔记存活。
- 代价：`app/core/task_registry.py` 成为后台任务的唯一入口，新增任务必须改两处。
- 再议条件：若将来出现进程级沙箱或外部任务队列，注册表可能被替代，本笔记需重估。

## Verification

- `backend/tests/test_task_registry.py` —— 异常记日志注销 / drain 取消清空 / 超时告警不抛出
- `backend/tests/test_shutdown_prewarm.py` —— 异常不外抛且留痕 / jieba 超时不挂死 / 正常与已取消路径
- `backend/tests/test_health_endpoints.py` —— 四态路由级（正常 / 调度器禁用 / DuckDB 降级 / OLTP 不可达 503）
- `frontend/src/lib/__tests__/admin-nav.test.ts` —— 导航 15 项与面包屑映射的等价断言，漏项即红
- `frontend/src/app/admin/sources/_batch-utils.test.ts`、`webhook-logs/_scope-utils.test.ts` —— 变异验证：把实现改回旧行为后转红
