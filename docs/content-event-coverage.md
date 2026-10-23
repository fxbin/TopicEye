# 同事件归并与报道阅读

## 事件事实与展示报道

PostgreSQL 的 `content_event_groups` / `content_event_members` 是事件事实源。
只有 active 组中 auto / confirmed 的成员参与折叠；shadow、pending、rejected
内容仍单独可见。旧 `content_relations.same_event` 只来自话题/标签相似，不能作为折叠依据。

持久化 canonical 保留最早报道或人工锁定的选择。首页与当日精选在当前筛选范围内
选择展示报道：正式分析优先，内容质量与风险先满足可读条件；在这些候选中尊重人工锁定，再优先已审核的一手/官方
信源档案、内容质量与精选分，最后按时间及 ID 决胜。这里只使用信源档案作为排序信号，
不据此宣称每篇文章经过独立事实核查。首页没有正式分析时仍保留原文章；精选的
local_fallback 内容继续留在待复核区，不占正式精选名额。

展示报道更换不修改 canonical。展开列表排除当前展示报道，必要时包含原始主报道。
`member_count` 为其余已接受报道数；`source_count` 是整个事件涉及的描述性来源数，
包括当前报道，不代表独立证据数量。`update_count` 为事件已接受的后续进展条数。

## 读取接口

- `GET /api/v1/contents?group_events=true`：先应用可见性、时间、来源、搜索、等级、标签
  筛选，再按事件选择代表、计数和分页。`total` 是筛选后的事件/独立内容数。
  默认 `group_events=false` 维持文章列表语义；事件视图支持三种时间排序，
  `curation_score` 与事件折叠组合会明确返回 400。
  `event_activity_at` 是当前筛选范围中事件用于排序的时间，前端时间流据此展示；
  原文章 `published_at` 保留。它是 ORM query_expression 读取投影，不是新增数据库列。
- 首页使用 `group_events=true&stable_feed=true` 开始浏览，响应增加 `feed_snapshot`。
  后续页必须原样携带该值，并保持页大小、筛选条件和用户身份不变。快照固定滚动时间窗，
  绑定筛选后的完整有序集合（代表 ID、事件键和排序时间），有效期 30 分钟。
  新内容、归并纠错或展示代表变化导致该顺序改变时返回 409；前端保留已加载内容，
  提供“刷新列表”从第一页重新开始，不能把新顺序的下一页追加到旧列表。
  这是浏览一致性令牌，不是鉴权凭据，也不保存正文历史版本。
  该路径每页重新核对有序 ID 集合，不使用普通列表的 L1 缓存；当前尚无生产大结果集性能结论。
- `GET /api/v1/contents/{id}/event`：保留原有 canonical + members 契约。
- `GET /api/v1/contents/{id}/event/coverage`：相对 `{id}` 返回其它报道；
  `member_offset` 默认 0，`member_limit` 默认 20、上限 20。
  响应含 event_id、version、canonical_id、representative_id、next_offset、has_more。
  后续页应携带 `expected_event_id` 和 `expected_version`；任一变化返回 409，从第一页重载。
  页面之间的版本保护覆盖事件成员与主报道变更，不是原文正文的历史版本系统。

coverage 的 relation_type 为 canonical / duplicate / corroboration / update。
公开覆盖信息不暴露内部推理、审核人或模型置信度。不存在与不可见文章统一返回 404；
可见但未归并的文章返回 `event: null`。筛选只限定主卡候选，用户展开时可以看到该事件
所有对自己可见且已接受的报道，不限于当前来源或搜索词。

后台接受/拒绝、调整/解锁主报道，以及 write 归一化成功提交后，立即失效当前进程的
首页与精选读缓存。失败事务与 shadow 运行不清缓存；幂等回放可以安全重复失效。
普通事件列表与精选还会在读取 L1 前查询 PG 的可见事件版本（组数、版本和及更新时间），
把该版本放入缓存键；其它 worker 提交纠错后，下次请求会绕过旧版本缓存。
该机制不覆盖其它类型的缓存，生产多实例拓扑和大事件集合的查询成本仍需单独验收。

## 自动识别边界

v2 先比较时间和明确产品版本：常规候选窗口 72 小时；跨窗口后续进展必须带明确的
产品/版本线索，并交由模型判断。不同明确版本不直接归为同一事件。
同来源、相同规范化标题的本地快速接受仅限 48 小时内，且摘要不能明显冲突；
非完全相同的标题即使很相似，也需要事实判断。

候选召回使用标题、摘要、明确版本以及实体/动作线索。召回分不是事实置信度。
一次边界调用可在多个候选中选择；返回的目标必须来自提供的候选集合。
同产品的发布、教程、价格调整，以及相同机构的不同新闻，需要分别判断。
模型不可用、响应非法、低置信度或达到调用上限时保持 pending，不隐藏文章。
每次条目数、候选数、并发、模型调用数、租约及幂等限制继续有效。

### 扫描进度与重试

成功运行的 `result` 保存完整的扫描/完成 ID 与独立内容候选，和可截断的详细
`predictions` 审计分开。shadow 按 owner、模式、分类器版本跳过已完成条目，
后续批次继续使用此前的临时候选；较早入库、较晚分析完成的文章仍会进入扫描。
进度与运行成功在同一事务提交，失败或回滚不推进进度。更换分类器版本并使用新幂等键后可以重评；
旧记录没有完整账本时允许重新扫描，不把截断审计当作完整进度。

临时模型故障/非法响应与预算延后保存在运行的 `retry_states` 中，不创建事件成员。
默认退避基数 `EVENT_NORMALIZATION_RETRY_BASE_SECONDS=900` 秒，
`EVENT_NORMALIZATION_RETRY_MAX_ATTEMPTS=3` 表示最多三次失败的模型尝试，之后明确 warning
并计入 `retry_exhausted`。预算延后不消耗失败次数；到期重试优先于新条目。
`retry_pending` 单独报告，兼容字段 `pending` 仍包含所有未确定条目。
低置信度或事实不确定的模型判断仍可创建待审成员，人工处理入口不变。
已有成员（包括旧版技术失败生成的 pending）继续保留，由后台复核；自动重试不覆盖已有审核关系。
模型等待期间新增的归属也在写入锁内重新检查：发生冲突时只跳过该条，保留人工的接受、拒绝、待审及理由，
并在 `skipped_conflicts` / `skipped_content_ids` 与逐条审计中明确报告。临时主报道已被其它事务占用时，
依赖它的建议也跳过；跳过项不计为已完成或临时独立候选，后续可按当前事实重新扫描。
默认定时扫描仍只处理最近 24 小时入库的内容，滑出窗口不会自动历史回填。

## 评估与逐步启用

`EVENT_NORMALIZATION_MODE` 默认为 off。开关不控制已确认事件的读取；off 只停止新的
自动识别，不能撤销已经接受的归并。shadow 只记录建议与运行审计，不写事件事实。

本地路由检查不访问数据库、不调用模型：

```bash
cd backend
uv run python scripts/evaluate_event_normalization.py --pairs /path/to/pairs.jsonl --output /path/to/report.json
```

每行应有 incoming、canonical（标题与显式时间戳；可附摘要/来源/标签）、
expected（same_event / different_event / unknown）、label_source。
输出区分“送到模型判断的候选召回”和“本地自动接受的精度”，未知标签不进精度分母。
合成回归或 agent 临时标注不等于人工留出集，也不能证明真实模型效果；该工具始终
标记 `model_accuracy_measured=false`、`write_rollout_eligible=false`。
它逐对检查已给定候选，不测完整历史池中前 8 名候选的竞争，也不测实际模型输出。

`scripts/evaluate_event_pool.py` 补充对给定候选池的前 K 名竞争、生产分类器响应解析与预算失败检查：

```bash
cd backend
# 默认只测召回，不调用模型、不访问数据库
uv run python scripts/evaluate_event_pool.py --dataset /path/to/pool.json --output /path/to/report.json
# 响应回放验证解析与错误路径；不能当作真实模型效果
uv run python scripts/evaluate_event_pool.py --dataset /path/to/pool.json --replay /path/to/responses.json --max-model-calls 20
# 只有明确选择 live 才调用实际模型；仍不写事件事实
uv run python scripts/evaluate_event_pool.py --dataset /path/to/holdout.json --live --max-model-calls 20
```

数据集包含 `dataset_id`、`split`、`pool_kind`、同一 owner 范围的 `candidates` 和 `queries`。
每个 candidate 是带唯一 `id`、标题及显式时间戳的内容投影，可带 `event_id`。
每个 query 包含 `query_id`、`incoming`、`expected`、`expected_target_ids`、
`target_labels_exhaustive` 与 `label_source`。正例可以只标已知目标；未标全的其它命中记为未知，
不能直接算误归并。`different_event` 必须针对整个给定池完成负例标注，单对负例不适用。
回放文件以 query_id 为键，值为 `{"response": {...}}` 或 `{"error": "..."}`。

输出绑定输入和分类器摘要，分别报告召回、误归并、弃权、失败、缺少回放与预算耗尽；
失败和 pending 留在全部已标注查询的分母。调用上限的单位是分类器请求，不代表底层 Provider
重试/切换的物理请求数或费用上限。解析接口没有返回确切模型身份和费用时，相关字段保持未知。
声明“完整池”或“人工标注”本身不构成验证；工具始终保持 `write_rollout_eligible=false`。
当前公开文章池压力样本也不等于实际历史 canonical 池或独立人工留出集。

建议的启用顺序与首轮验收门槛（尚未验证通过，不代表生产现状）：

1. 先完成隔离回归，再在经授权的环境用 shadow 收集真实输出。保持模型预算和幂等键；
   不反复重跑同一批来挑选更好的结果。
2. 用与校准集分离、人工判定的留出集复核自动接受结果。覆盖中文/英文、同源/跨源、
   异标题、跨日、不同版本、泛化同名、教程与发布混淆，以及私有范围。至少复核
   400 个自动接受的真实样本，精度的 95% Wilson 下界不低于 99%；另复核至少
   200 个容易混淆的负例，不能出现错误隐藏。失败、超时、pending 与未召回分别报告，
   不从分母里静默删除。重复报道减少量与模型费用单独报告。
3. 通过后先人工运行一批有界 write（短时间窗、限制条数），回读归并列表与前端展开。
   复核无误再考虑开启定时 write；开启前记录准确配置、样本摘要、预算和回退负责人。
4. 发现误归并先停止新的自动 write，再在后台拒绝错误成员，使文章重新独立展示；
   必要时按版本调整/解锁主报道。保留审计和原文，不通过删数据回退。

未达到真实样本门槛时，交付代码与评估结果，保持生产自动 write 关闭。

## 回归入口

```bash
TEST_PG_PORT=5543 bash backend/scripts/test_full_local.sh -k 'content_event or event_coverage_feed or today_picks or contents_server_filters or cache_warmup or json_cache'
cd frontend && npm run test -- src/lib/event-coverage.test.ts src/lib/__tests__/content-events-api.test.ts
```

禁止直接把后端 pytest 指向开发库；全局 fixture 会清空它指向的 PostgreSQL。
