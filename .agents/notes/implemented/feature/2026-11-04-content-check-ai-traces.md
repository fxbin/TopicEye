# Agent Note: 文稿检测 AI 痕迹维度合同

Status: implemented — #228 一期启发式统计；无持久化、无迁移

## Problem

用 AI 辅助写作的创作者想知道文稿「AI 味」重不重、具体重在哪。既有链路只有
风险把关（违禁词/极限词/限流词），没有写作风格信号。本轮新增 ai_traces 维度：
AI 高频词/黑话命中、套话连接词命中、句式均匀度，各自分档 + 综合建议。

## Decision

### 定位红线：启发式统计，不是模型检测

全链路（响应字段、advice、UI 文案、hover 提示）明示「启发式统计」，禁止
「AI 率 / AI 概率 / 检测模型」类口径——词库命中与句式统计都判不了文稿来源。
与风险把关语义分开：ai_traces 独立端点独立展示，**不并入 /sensitive 的
total，不影响「未发现违禁词，可以发布」结论**（风险把关与写作建议不同层）。
现链路无全局总分/评分体系，本轮不新造。

### 词库（backend/app/core/ai_traces/ai_lexicon.json）

`_meta` + 两组词条：`buzzword` 154 条（预算 100~200）、`connective` 39 条
（预算 30~50）。**人工整理**（大模型中文输出的词频观察 + 通行互联网黑话），
无单一权威来源，`_meta.source` 如实标注；若逐词要求外部背书会滑向 4/5 工作量，
首版放弃。词条校验同敏感词：不含空白/标点，非法词条显式 warning 跳过，
测试断言零跳过 + 无重复 + 预算区间。加词走普通 PR，更新改 `version_date`。

刻意排除：通用副词单用（显著/极大）、正常书面语常用词（但是/因此），只收
堆积才有信号的黑话与套话，控制口语化文稿的误报。

### 扫描与偏移（沿用敏感词既有合同，改动两边一起改）

分隔符 `[\s\W]` 1:1 掩码、每维度按词长降序 union 正则（同 start 保留最长）、
start/end 是原文 codepoint 偏移、不做 NFKC。两维度命中合并后按
(start 升序, 长度降序, buzzword 先于 connective) 贪心去重叠，区间两两不交
——前端 `_highlight.tsx` 按 codepoint 切分对齐（emoji 不漂移）。

### 分档阈值（service 显式常量，改阈值必须同步测试边界断言）

- 密度 = 命中次数 / 全文 codepoint 数 × 1000（次/千字，分母含标点空白）。
  buzzword：≥3 起 medium、≥8 high——黑话在口语化写作几乎不出现，阈值从宽。
  connective：≥2.5 起 medium、≥6 high——首先/其次在正常议论文有基础出现率，
  阈值不能压太低误伤正常行文。
- 句式均匀度：按中文句末标点（。！？；…全半角）与换行分句，句长取 codepoint
  数，用 **CV=pstdev/mean**（无量纲，长短文可比）而非原始方差；
  CV<0.20 high、0.20≤CV<0.35 medium、≥0.35 low。自然中文写作句长长短交错
  （口语样本实测 CV≈0.76），模板化行文句长趋同（密集样文实测 CV≈0.07）。
- **insufficient 边界**：句数 <3 时 CV 无统计意义，rhythm 返回 insufficient
  且 cv=null，不编造分档。词证据与句证据独立：短文本黑话密集仍按词分档
  （word hits 参与整体）；只有「句数不足且词零命中」时整体才 insufficient——
  短到没有任何可信信号时宁可不判，也不编造「痕迹少」。

### 入口与前端

- `POST /api/v1/content-check/ai-traces`：挂在 /content-check 路由器上共享
  `get_current_user` 与限流；`max_length=20000` 与 sensitive 同口径（422）。
- 前端 `/content-check`：开始检测时两请求 `Promise.all` 并行，结果合并成
  单一对象进 `_scan-state` 的快照合同（泛型化后两类结果一起 current/stale）。
  右侧新增 AI 痕迹面板（三子指标 + 分档 Badge + advice）；正文高亮合并渲染：
  风险命中红/黄系不变，AI 痕迹命中**紫色系**（设计系统 --color-purple），
  同区间重叠时风险命中优先。「未发现违禁词，可以发布」只看 sensitive.total。

### 测试口径

`tests/test_ai_traces.py`：词表零跳过/预算、偏移切片还原（含 emoji）、密度与
CV 分档边界等值行为、insufficient 边界、401/422、万字基准（均值 <500ms，
实测远低于此）。跑法同敏感词：一次性 PG 单跑或 `make test-backend`。
零回归验证：`tests/test_sensitive_word.py` 未改动、单跑通过；前端
`npm run test:coverage` 通过（_scan-state / _highlight 用例同步扩）。

## 后续（v2 再议）

全局总分/评分体系、逐句均匀度高亮（v1 只做词级定位）、改写建议生成、
词库入库与用户自定义、英文文稿。
