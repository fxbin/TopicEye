# Agent Note: 自然语言兴趣描述提取母题关键词的取舍

Status: implemented — #187 由竞品功能雷达推进，用户侧页面落地，admin 母题页未接入

## Problem

母题 keywords 一直只能手工逐个填写，用户要先想清楚「用什么词才能命中文章标题」。TrendRadar 的 ai_interests.txt 证明「一句话描述兴趣 → 自动出关键词 → 用户确认」是被验证过的形态。要接入就得回答：兴趣描述存不存库、LLM 给的词和打分引擎对不对得上、LLM 接口怎么防刷。

## Decision

- **兴趣描述不存库，只用于这一次提取**。`mother_topics.description` 是 String(200)，500 字描述写进去 PG 直接超长报错，扩列就要迁移；提取接口做成只读（不写库、不需要 topic_id），勾选后的词经既有 POST/PUT 落库，落库路径和手工填词完全相同——「行为一致」由设计本身保证，不靠测试模拟。
- **数量下限不凑数**。提示词要求 5-15 个；服务端清洗后最多截到 15 个，剩 1-4 个按实际返回（前端显示实际个数），清洗后为 0 抛 `KeywordExtractionError`（502）。服务端硬凑到 5 个就是编造。
- **限流 30 次/分钟**（与 creation 同档，前缀规则置于 `/api/v1` 兜底之前）。预算熔断三窗默认 0（关闭，config.py `LLM_BUDGET_*`），这个接口按 description 逐次烧钱，必须靠限流兜底。
- **关键词写法受子串匹配约束，写进提示词**。match_score 是不分大小写的子串匹配（`mother_topic.py:74-75`），所以提示词要求：2-8 个汉字的具体概念或具体英文产品名/品牌名，优先用文章标题里会原样出现的写法并给常见别名；禁止句子、「内容/资讯/相关」类泛词、单独两个字母以内的英文缩写（单独 "AI" 会子串命中 said）。

## Alternatives considered

- 兴趣描述扩列存库：被否——仅为一次性提取引入迁移与回滚成本，不值得。
- 提取接口直接写回母题（传 topic_id）：被否——绕过 `_assert_can_modify` 之外还得复刻一套写入路径，勾选确认是产品语义的一部分，不能省。
- admin 母题页同步接入：本轮裁剪——admin 页有一份独立的 TopicCard 拷贝，接入是纯复制粘贴但扩大验证面；用户侧先验证形态价值。

## Consequences

- 同一段描述重复提取命中 LLM 响应缓存是预期行为（不绕过缓存）；改描述才会产生新调用。
- LLM 给的词与标题对不对得上，最终靠用户逐个勾选兜底——已有的词标「已有」置灰不可勾选、新词默认勾选、合并时不分大小写去重。
- admin 页接入、持续/自动解析兴趣描述，留待该形态在用户侧验证后另开 issue。

## Verification

`backend/tests/test_mother_topic_keywords.py`（LLM 全 mock）：service 清洗/去重/截断/异常上抛、接口 200/422/401/502 全档位、提取前后 mother_topics 行数不变、提取结果经 PUT 写入后与手工填同一组词的母题 score-batch keyword_score 完全一致、`_match_rule` 命中 (30, 60)。前端 `_keyword-extract.test.ts` 锁定切分/标注/合并三函数与页面既有英文逗号口径一致。
