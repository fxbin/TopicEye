# Agent Note: 前端体验指标（LCP/INP/CLS）观测合同

Status: implemented — #179（Owner 选定「先补度量」路线），Worker 实施

## Problem

系统内只有服务端指标（http / LLM / DB 连接池 / 进程 / 慢查询），没有任何「用户端首屏体验」的度量面。LCP 出了 bad，系统内没有任何数据能回答三个问题：差在哪、哪个路由差、从什么时候开始差。

这不是抽象担忧——本仓库首页的结构决定了 LCP 必然难看：`frontend/src/app/page.tsx` 整页 `'use client'`，内容列表在 `useEffect` 里 `contentsApi.list(...)` 才回来，而 `frontend/src/app/layout.tsx` 的 SSR 预取只覆盖 auth/me、feature-flags 和三个计数，**不含内容列表**。于是首屏 LCP 元素（首张选题卡的文本块）必须等「JS bundle → hydration → 客户端 `/api/v1/contents` 往返 → 渲染」。

## Decision

分两步走，本次只做**度量**：

1. 先让 LCP 成为系统内可观测的指标（本次）
2. 再改首页数据路径把数值压下来（独立工作项，本次明确不做）

理由：没有度量就无法判断第 2 步有没有效果，也无法回归。

## 观测面归属

**落在后端自带的监控大盘 `/dashboard`，不新建 Next.js 后台页。**

`/dashboard` 由 `backend/app/api/dashboard.py` 直出 HTML（Canvas 图表），轮询 `/api/v1/metrics/snapshot`，并经 `next.config.js` 的 rewrite 以同源 `/dashboard` 暴露。扩展它避免了新增导航项、面包屑映射与 admin 壳测试，改动面最小。

「前端体验」是该大盘的新增 Tab：KPI 卡（LCP/INP/CLS 的 p75 + 档位）+ 按路由拆解表，可切换「首次加载 / 软导航 / 全部」。

## 口径合同（唯一真源在 service 层）

`backend/app/services/web_vitals_service.py`：

- **阈值**（与浏览器侧 web-vitals v6 一致）：LCP 2500/4000 ms、INP 200/500 ms、CLS 0.1/0.25、FCP 1800/3000 ms、TTFB 800/1800 ms。判定语义：等于 good 上界仍是 good，严格大于才是 needs-improvement。**服务端算，不采信客户端上报的 `rating`。**
- **p75 用最近秩法**（排序后取第 `ceil(0.75 × N)` 个），不是 PostgreSQL 的 `percentile_cont`：后者只 PG/DuckDB 有，SQLite 没有，测试跑不起来；且最近秩没有插值，结论可复现。排名表达式用纯乘法比较（`(rn-1)×100 < total×p ≤ rn×100`）而不是除法——SQLAlchemy 2.0 里整数列的 `/` 会渲染成真除法，截断语义会丢。
- **路径归一在服务端做**（`normalize_route_path`）：纯数字段与 UUID 段 → `[id]`，静态段原样保留（`/admin/model-eval` 不能被误伤）。归一后路径基数不随内容 id 增长。归一规则只有这一处，前端发原始 pathname，不在前端另抄一份。
- **不存原始 User-Agent**，只存派生的 `device_class`（mobile/desktop/tablet/unknown）。
- **保留期 30 天**（`RETENTION_DAYS`），与 `metrics_snapshots` 的 7 天分开——逐条样本量级远大于聚合快照。清理挂在 scheduler 的 `web_vitals_cleanup`（每日 03:30）。

## 上报链路

`frontend/src/components/WebVitalsReporter.tsx` 用 Next 内置 `useReportWebVitals` 订阅 LCP/INP/CLS/FCP/TTFB，经 `navigator.sendBeacon` 发到同源 `/api/v1/metrics/web-vitals`（前端有 `/api/:path*` rewrite 到后端，故同源、cookie 随行、无需 CORS 预检）。

两条纪律：

- **不拖累被观测的指标**：sendBeacon 不阻塞渲染，失败一律静默；上报代码不进首屏关键路径。
- **回调要稳定**：web-vitals 的观察器按回调引用注册，回调每次换会把观察器重挂一遍、可能重复上报。**靠 ref 长期持有同一个回调实例**（结构保证），不是靠 `useCallback` 的依赖数组写对（约定保证）。payload 整形与失败静默抽进 `createWebVitalReporter`（纯函数、可单测）。

## 端点与权限

- `POST /api/v1/metrics/web-vitals`：**登录可选**。`/metrics` 那个 router 整体带 `get_current_admin_user`，若把接收端点挂进去，未登录用户将完全无法上报——而登录页恰恰是最该被观测的页面。非法条目（metric 不在白名单、值越界、路径超长）**逐条丢弃**，不整批失败、不 500。
- `GET /api/v1/metrics/web-vitals/summary`：**管理员**。返回窗口内各指标 p50/p75/p95 与按路由的 p75 拆解。

**形状校验与语义校验的分界**：schema 只管形状（是不是列表、字段在不在、条数 ≤20、value 是数字），语义一律交给 service 逐条判定。字段长度上限刻意放宽（path ≤512、metric ≤64），这样一笔脏数据只会让**它自己**被丢掉，不会把同批合法样本一起打成 422。早期版本 path 带 `min_length=1`、导航类型带 `max_length=20`，结果「空路径按 / 归一」这条 service 逻辑永远走不到——schema 与 service 自相矛盾，独立复核时被抓出来。

## 明确不做（避免下次又绕一圈）

- 不改首页数据路径（`app/page.tsx` 的客户端取数）——那是修数值那条路
- 不动 `globals.css` 的 `fade-in` 动画（它从 `opacity: 0` 起步，动画期间元素不具备 LCP 候选资格，确实在推高 LCP，但属修数值那条路）
- 不把 web vitals 灌进 DuckDB：这是新的遥测域，与内容分析域不同源，事实源与聚合同在 PG
- 不接告警（`services/metrics_alerting.py` 未动）
- 不做用户级明细视图，只做路由级 p75

## 独立复核发现的三处（已修）

1. **schema 与 service 自相矛盾**（中低）：见上面「形状校验与语义校验的分界」。修法是放宽 schema 的字段上限、让语义一律逐条判定。
2. **DB 失败守卫零测试保护**（中）：删掉 `report_web_vitals` 的 try/except 后全部用例仍绿——这条最容易在重构中被删掉的保护逻辑没有回归测试。已补：monkeypatch 让写入抛错，断言返回 202 + `accepted=0`，并断言随后的聚合查询仍 200（证明回滚生效、会话没被带坏）。
3. **路由前 40 的排名口径**（低）：原先从被截断的 (path, metric) 组反推每路径样本数，组数超 300 时部分路径计数被低估、排名跟着错。已改为单独按路径统计样本数来挑 top-40。

顺带修正：文档里把浏览器侧库写成 v5，实际 Next 16.4.1 打包的是 **v6**（metric id 前缀 `v6-`）；阈值与判定式两版完全一致（LCP 2500/4000、INP 200/500、CLS 0.1/0.25、FCP 1800/3000、TTFB 800/1800），所以结论不受影响，但版本号不能写错。

## 遗留

- 真实 p75 需上线后由现场样本产生；本次交付不含真实浏览器端 Lighthouse 验收，验收口径是「链路可运行 + 口径有单测 + 面板可见」。
- 样本量上来后的聚合查询性能未压测；当前窗口最大 30 天，路由拆解按样本数取前 40 条。
- **软导航口径在多数浏览器恒为空**：只有支持 `soft-navigation` entry type 的浏览器才会把 navigationType 记成 soft-navigation。服务端白名单接受该值（非错误），大盘空态已给出说明。
- **限流桶按 client IP 分**：公司出口与移动网络 CGNAT 下多用户共用一个 IP，桶给到 300 次/分钟（≈60 次页面浏览/分钟/IP）；429 对 sendBeacon 不可见（静默吞掉），表现为样本静默缺失。
- **组件跨渲染的回调稳定性没有测试锁住**：仓库不引 jsdom（`vitest.config.ts` 里写明了这是既定决定），只能测到「渲染不炸 + 注册了采集器」。现在靠 ref 持有回调（结构保证）而不是靠 `useCallback` 依赖数组（约定保证），但若有人把 ref 改成每次渲染新建，仍不会被测试发现。
- **开发态 StrictMode 双注册未实测**：`next.config.js` 有 `reactStrictMode: true`，React 19 在 StrictMode 下双调用 effect，而 `useReportWebVitals` 的 effect 无 cleanup，怀疑开发环境会注册两套观察器。生产构建不受影响。无 DOM 测试环境，此项**未验证**。
