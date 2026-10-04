# Agent Note: 删掉「九项关键流程」对照表

Status: implemented — 2026-10-04 对照表删除，改留可靠手段

## Problem

`AGENTS.md` §三 有一张「九项关键流程」表，把改动模块映射到该验的业务链路。
它从已删除的 `docs/quality/regression-matrix.md` §三 继承而来。

表本身有个说不清的问题：它是 `backend/tests/` 下 130+ 个测试文件里挑出的 9 个，
既不完整（notification、personalization、topic_clustering、各类 digest、
review / read_record / favorite 等整条链路都不在表里），也不是划分（几条链路跨多组测试）。
但「九项」这个数字读起来像一份完整清单。

## Alternatives considered

- **保留表格，只压缩措辞。** 否决。问题不在措辞，在于它无法自证完整，而读者会当它完整。
- **重写成「跨模块连带影响」清单**（如：改 DuckDB 查询连带验回退路径、改评分连带验排序与推荐档位）。否决。
  动笔前逐条核实，结果是原表的映射本来就是松的：
  - `test_db_backend` 测的是 DuckDB ATTACH PostgreSQL 的连接层（profile / attach SQL / 密钥脱敏）
  - `test_digest_fallback` 测的是日报兜底内容的生成（editorial lead + feature cards）
  - `test_lifespan_duckdb_init` 测的是启动时 DuckDB 卡住不冻死 event loop

  三者都与「DuckDB 不可用 → OLTP 回退」沾边，但不是同一件事。写新清单等于往 agent
  指令文件里塞一批当场没验过的断言，代价是新增漂移面。
- **删表，留可靠手段。** 采纳。

## Consequences

- §三.2 改为「改了什么，就验什么」，给出两个可靠办法：`git log --name-only -5 -- <改动文件>`
  找历史共变的测试，或 `make test-backend` 直接跑全量。
- 保留一句提醒：挑着跑时要自己盯住第一节那两件事（读写落在 Postgres 还是 DuckDB、
  分析结果是不是 `local_fallback` 假分）。这是 #90 事故留下的、真正非显然的部分。
- 顺带修掉一个悬空引用：§三.3 末尾「第 5 项注意」指向的是一个已不存在的编号列表，
  把 `-k` 是全局过滤器的警告并进 Backend tests 那一条 bullet。
- `.agents/notes/README.md` 的分工表同步（原写「九项关键流程的验证命令」）。
- 本笔记不改写 `2026-10-03-registry-ten-dimensions-to-three.md`——它记录的是当时的
  状态，按 notes 契约「决策被推翻时新建笔记并双向链接，不改写旧文」。

## Consequences（再次强调，勿重复踩）

给 agent 的指令文件里，**「列出来的东西」会被当成「全部」**。写清单前先回答：
这份清单能自证完整吗？不能就只给找它的办法，不要给清单本身。
