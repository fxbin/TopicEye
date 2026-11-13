# Agent Note: 文稿检测 AI 痕迹维度合同

Status: implemented — #228 一期启发式统计；#241 改写建议（检测→改写闭环）；无持久化、无迁移（prompt_registry 只加数据行）

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

### 改写建议（检测→改写闭环，#241）

对 AI 痕迹命中密集的句子生成「保留原意的口语化改写」。长期合同：

- **请求体 = 全文，不是句列表**：分句正则与词库命中只在后端一份
  （ai_trace_service）；若前端传目标句，TS 必须重复实现分句+命中归因，词库
  口径双份漂移。「限流」的意图改由后端实现：只有服务端选取的 ≤3 句进入
  LLM prompt，**全文永不进 prompt**（20000 字请求体 ≠ 20000 字 prompt）。
- **选句规则**（humanize_rewrite_service.select_target_sentences 纯函数）：
  逐句 scan_words 统计句内命中（句末标点属掩码分隔符，词命中不可能跨句界，
  逐句重扫与全扫在句内等价——测试锁该等价性）；命中数降序（同数按原文顺序）
  取前 3，零命中句不入选。**没有「句数不足 422」**：1~2 句有命中照样改写，
  响应建议数 <3 即可；只有选取结果为空（全文零命中）才 422 显式原因。
- **响应不信 LLM 回显**：条目必须与服务端选取句逐字对应，original 以服务端
  为准；hit_words 逐条对照该句真实 scan_words 过滤（LLM 编造词进不了徽标），
  LLM 未回显时退回该句真实命中，不空着也不编造。
- **数字/事实一致性不硬校验**：「3 个方法」→「三个方法」是合法改写，运行时
  硬校验会误杀。可测口径 = prompt 显式指令（照抄时间/数字/专有名词/结论）+
  mock 测试断言响应管道逐字透传。真实 LLM 服从性无法确定性保证，UI 文案
  明示「发布前请自行核对事实与数字」。
- 错误映射照 content_events 先例：LLM 链路异常（熔断/容量/预算/上下文）与
  不可解析输出 → 502 显式中文文案；零命中 → 422；401 由 router 级
  get_current_user 覆盖。文案红线沿用：改写是「写作建议」，禁止「AI 率/
  概率/检测模型」表述，也不暗示能改变文稿来源判定。
- 模块边界：humanize_rewrite_service 有 LLM IO，**不并入** ai_trace_service
  （后者合同是纯启发式统计无 IO）；prompt 收进 llm/prompts/humanize_rewrite.py
  并注册 prompt_registry（scene=humanize_rewrite，无 schema 变更）。
- 前端：AI 痕迹面板下加「生成改写建议」按钮（_humanize.tsx，紫色系徽标），
  按钮禁用条件 = phase 非 current 或 aiTraces.hits 为空（scanPhase 合同保证
  current 时 text===scannedText，建议与展示结果同一文稿快照）；建议 state 随
  重扫/清空作废；生成错误独立 inline 展示，不复用检测的 ErrorState 重试语义。

### 测试口径

`tests/test_ai_traces.py`：词表零跳过/预算、偏移切片还原（含 emoji）、密度与
CV 分档边界等值行为、insufficient 边界、401/422、万字基准（均值 <500ms，
实测远低于此）。跑法同敏感词：一次性 PG 单跑或 `make test-backend`。
零回归验证：`tests/test_sensitive_word.py` 未改动、单跑通过；前端
`npm run test:coverage` 通过（_scan-state / _highlight 用例同步扩）。

改写闭环（#241）加 `tests/test_humanize_rewrite.py`：选句纯函数（优先级/
补足/上限/零命中/逐句重扫等价）、mock call_llm_json 的成功路径（hit_words
过滤、original=服务端选取句、数字逐字透传、prompt 含不改事实指令且全文不进
prompt）、LLM 异常→502、零命中→422、401、超长 422；前端 `_humanize.test.tsx`
渲染对照（建议句/紫色徽标/禁用态/独立 inline 错误）。

## 后续（v2 再议）

全局总分/评分体系、逐句均匀度高亮（v1 只做词级定位）、改写建议的 diff 高亮
对齐/一键替换/风格模板/改写回写检测（#241 只做生成与展示）、词库入库与用户
自定义、英文文稿。
