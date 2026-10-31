# Agent Note: 文稿违禁词/广告法极限词检测合同

Status: implemented — #175 一期纯函数扫描链路；无持久化、无迁移

## Problem

内容创作者发布前需要快速知道文稿里踩了哪些广告法极限词、高危违禁词与平台限流词。
这是一次性「检测工具」，不是内容治理流水线：不改评分入库，不碰 /skill 与 MCP 出口，
不做用户自定义词库（那需要新表，v2 再议）。

## Decision

### 词库（backend/app/core/sensitive_words/）

三份静态 JSON，总量 583 词（预算 ≤1000）：`advertising_extreme.json`（246）、
`political_adult.json`（204）、`platform_throttle.json`（133）。每条
`{word, severity(high|medium|low), suggestion?}`。

- **JSON 无注释语法，「文件头注明来源/License/版本日期」以 `_meta` 字段落在首个 key**。
  来源：广告法第九条（法条，无著作权）+ [advertising_law_checker](https://github.com/521xueweihan/advertising_law_checker)（MIT）
  与 [Sensitive-lexicon](https://github.com/konsheng/Sensitive-lexicon)（MIT）的人工筛取；
  政治类刻意只取高频基础词，不搬完整开源库（误报失控）。
- **更新口径**：加词走普通 PR；词条不得包含空白/标点字符（service 加载时校验，非法词条
  显式 warning 并跳过，测试断言内置词库零跳过）；一个词只归一个文件，跨文件重复以
  「更像哪类风险」为准归属。限流词随平台规则漂移最快，复核频率高于另两类。
  每次更新改对应文件 `_meta.version_date`。
- severity 判档：法定绝对化/违法高危=high，arguable=medium，流行语/轻度=low。
  单字面「第一」定 medium 并带序数豁免提示——「第一次体验」类误报留给使用者按严重度取舍。

### 匹配与偏移口径（改动必须前后端同改）

- `scan()` 纯函数：三类各一个按**词长降序**的 union 正则（`re.escape`，零第三方依赖）。
  Python re 的 alternation 是分支左侧优先而非最长优先，**降序排列是实现「同 start 保留
  最长」的前提**，不是优化细节。
- 全角/半角标点与空白是分隔符：扫描前把 `[\s\W]` 1:1 替换为 `\x00`，词条不含分隔符，
  因此不可能跨标点命中且偏移不变。
- **start/end 是原文字符（Unicode codepoint）偏移，不做 NFKC**——归一会令偏移漂移、
  前端高亮错位。前端 `_highlight.tsx` 因此用 `Array.from` 按 codepoint 切分，不能用
  UTF-16 下标直切（emoji 错位）。全半角折叠与繁体均不承诺。
- 重叠合并：按 (start 升序, 长度降序, 严重度降序, category 名) 排序后贪心扫，
  结果区间两两不交；错位重叠先出现者保留，同区间高严重度胜出。
- `functools.cache`（即无界 lru_cache）缓存词库与编译结果；实测 286 词/类 union
  编译 1.74ms、1 万字扫描 0.21ms，距 200ms 预算约三个数量级余量，无引入
  Aho-Corasick 类依赖的理由（也避免动 uv.lock）。

### 入口与前端

- `POST /api/v1/content-check/sensitive`：`Depends(get_current_user)` 防匿名刷大文本；
  限流由 `/api/v1` 前缀全局中间件自动覆盖（200 req/min），**不单列规则行**。
  `text` 用 Pydantic `max_length=20000` 自动 422。
- 前端 `/content-check`（创作空间，access: 'user'）：文本框 + 右侧分类/严重度统计 +
  正文高亮，hover 走原生 `title`（无 JS 态也可达）。高亮渲染拆在
  `src/app/content-check/_highlight.tsx`。
- **检测结果只对检测时的文稿快照有效**（评审阻断项回归）：编辑即 stale，
  判定合同在 `src/app/content-check/_scan-state.ts` 并有测试锁定。stale 态既不展示
  「可以发布」类把关结论，也不用旧偏移在新文本上高亮（范围内错位无法靠
  `_highlight` 的防御挡住）；两个模块均已纳入 vitest 覆盖率门禁。
- 组件测试不引 jsdom：沿用 `react-dom/server` 的 `renderToStaticMarkup` 先例
  （Badge.test.ts），vitest include 从 `*.test.ts` 扩到 `*.test.{ts,tsx}`。

### 测试口径

`bash backend/scripts/test_full_local.sh tests/test_sensitive_word.py`——注意该脚本
把 `tests/` 写死在参数前，追加文件参数会被吞并，**实际跑的是全量套件**；迭代期可自起
一次性 PG 单跑 `tests/test_sensitive_word.py`。基准断言（1 万字多次均值 < 200ms）在
同文件内，防性能回归。
