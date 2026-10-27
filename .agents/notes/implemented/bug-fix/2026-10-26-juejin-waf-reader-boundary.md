# Agent Note: 掘金反爬挡站内阅读的根因与修复边界

Status: implemented — PR #162（识别挑战页 + 失败冷却）、PR #163（入库补全文）落地；状态以 GitHub 为准。

## Problem

掘金文章点「站内阅读」报 `not_readerable`「该页面没有可提取的正文」，但页面本身有完整 SSR 正文。

根因（本地复现，2026-10-26）：掘金（字节 WAF）按 IP 频率限流，被标记后返回 **HTTP 200 的 JS 挑战空壳页**（约 2.5KB，含 `waf_jschallenge`/`_wafchallengeid`，前端跑 SHA-256 PoW 种 cookie 后重载）。httpx 与 curl_cffi（浏览器 TLS 指纹）两层拿到同一空壳页——**限流是 IP 维度，换 TLS 指纹无效**。trafilatura + 手工回退双路提取凑不够 60 字阈值 → fail-closed 报错误导用户的文案。拦截窗口实测分钟级（约 15 分钟自动解除）；同机 6 连抓第 5、6 次连续失败，且失败期间用户每次点击都会再打一次源站、加深限流。

## Decision

两条互补的修复线，让掘金条目点击时**根本不外呼**、真被挡时**报错诚实且不火上浇油**：

1. **reader 侧（PR #162）**：响应体签名识别挑战页（字节两家 + Cloudflare `cdn-cgi/challenge-platform`，匹配带 64KB 体积上限防讨论反爬的长文误判）→ 独立错误码 `anti_bot_challenge`（503）；`anti_bot_challenge` 不进 `_no_retry`（TLS 型挑战 curl_cffi 仍可能救回）。失败按 content_id 进程内负缓存 `ARTICLE_READER_FAILURE_COOLDOWN_SECONDS`（默认 120s，0 关闭），期内重抛上次错误零外呼，`refresh=true` 绕过、成功清除。
2. **ingest 侧（PR #163）**：入库管线去重后、落库前对 `INGEST_FULLTEXT_HOSTS`（默认 `juejin.cn`）缺正文候选预抓一次原文，重建受控 HTML 存 `raw_content`；每 sync 上限 6 + 进程级 2s 最小间隔；fail-open 绝不阻断入库。

## Alternatives considered

- **掘金 content detail API**（`content_api/v1/article/detail`）：实测对数字 article_id 不开放——int 报 404「内容为空」、string 报「参数错误」，内部走 UUID 且推荐流无映射字段；推荐流本身只带 ~90 字 brief。死路，勿再试。
- **服务端解 WAF PoW / 种 cookie 伪装通过**：等于绕过反爬，违反 article_reader 头部声明的设计契约（no cookies / no stealth escalation，受保护页面回退外链）。明确不做；若有再提议，先推翻该契约。

## Consequences

- 冷却是进程级（与 `_robots_cache` 同口径）：多 worker 部署时各进程独立冷却，仅损失节流精度，无正确性问题。
- 120s 冷却窗口 ≈ 拦截窗口下限的量级估计，非实测对齐；若掘金窗口变长，调 `ARTICLE_READER_FAILURE_COOLDOWN_SECONDS` 即可，无需改代码。
- 挑战页签名是白名单式（字节 + Cloudflare）：其它 WAF（如阿里云）出现时同样表现为 `not_readerable`，按需补 marker。
- ingest 补全只处理去重后的新候选：存量缺正文条目不回填，站内阅读回退点击时抓取（#160 冷却兜底）。

## Verification

- 单元/回归：`tests/test_article_reader.py`（19 用例，含真实挑战页样本的分类与冷却计数）、`tests/test_content_enrichment.py`（6 用例）、`tests/test_content_pipeline.py` 接线测试；后端全量 1372 通过。
- 挑战页样本取自 2026-10-26 实际拦截响应（精简保留签名特征）。
