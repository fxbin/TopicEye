# 日报归属与生成版本的一致性

Status: implemented
Issue: #136

## 为什么把隔离放在每个查询与投递出口

`DailyReport` 同时存公共日报和用户私有日报。仅 `/me/*` 按用户筛选不够：公共列表、总数和日历都必须显式 `owner_user_id IS NULL`；日历也会返回摘要、条数与时间，不能当成无敏感数据的索引。趋势桶查询同样必须限制为公共内容或当前用户可见内容。

私有日报成功/失败通知定向所属用户；共享群 webhook 在 service 出口拒绝任何私有日报，即使调用者设置 force。前端隐藏推送按钮只改善交互，不能代替这一服务端保护。

机器回归：`backend/tests/test_daily_report_audit.py` 使用一次性 PostgreSQL 验证公共列表/总数/日历、版本读权限、趋势查询与私有通知投递。不得连接开发库运行这些测试。

## 为什么冻结 cutoff 并按 ID 轮询

旧异步入口创建的占位与 worker 会各自确定 cutoff；时间一变，worker 可能创建另一行，占位停在 GENERATING。按日期轮询又可能因 final 优先而提前拿到旧 DONE。

异步入口现在冻结带明确时区的截止时间，与 worker 共用；响应返回版本 ID，前端只查询该 ID 的归属受限端点，并直接展示该版本。失败先 rollback，再标记同一 ID。PostgreSQL 公共行 owner 为 NULL，普通多列 UNIQUE 不能防重复；异步 starter 用事务 advisory lock 串行化同 owner/date/edition 的领取。独立 PG 会话并发回归验证只产生一个 starter 任务。

该并发证据不覆盖旧同步 `/generate`、调度器多进程及超过十分钟的接管；不据此宣称整个系统 exactly-once。历史数据库中已写错时区的记录没有批量改写。

## 为什么前端统一请求归属和日期运算

正文、标记、昨日追踪与曲线都属于同一次导航。旧响应必须在状态写入前验证代际；副数据不应阻塞阅读。标记的乐观更新要保留刷新前的本地操作，并在保存失败时恢复，不能污染另一期。

报告日期遵循上海时区；前后日运算必须在 ISO 日期上执行 UTC 算术，不能混用浏览器本地 noon 与上海格式化。创作链接由一个 helper 生成，头题、次题、速览与已选抽屉都带选题标题和原文 URL。

机器回归：`_report-loader.test.ts`、`_daily-utils.test.ts`、`_frontpage.test.ts`；浏览器 fixture 流程证据留在 `.vidt/daily-audit-20261022/`。fixture 与人工内容只证明本地页面和接口契约，不证明真实 LLM、生产数据或群投递。
