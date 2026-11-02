# 日期版本与产品里程碑更新记录

Status: implemented — 更新内容按日期里程碑整理，数据库保持展示事实源

## 问题

旧记录把技术提交、未来计划和已经完成的变化混在一起，版本从 v0.13 回到 v0.4 的规划；条目标题没有显示，且每条都复用版本 edited 时间标注相对日期，导致编辑旧记录后像是刚发生。用户明确允许完全重整，并选择日期版本。

## 决定

- 一个日期版本对应一个更新主题、一段摘要和几条用户能感知的变化。日期统一为 `YYYY.MM.DD`，不同输入写法规范化后查重；同日补充内容编辑已有记录。
- 12 个历史里程碑、43 条变化记录在 `backend/app/data/release_notes.json`，每组保留支持其内容的 Git hash、committer 时间和标题。Git 记录只能证明代码阶段，不追认真实生产上线时间。
- 历史版本日期是归档日期，实际生产上线时间未知时 `shipped_at` 保持空；创建和编辑均不自动补当前时间。记录公开状态与实际软件上线时间是两件事。
- 版本主题使用已有 `product_updates.title`，摘要使用已有 `description` 列并在 API 中称为 `summary`；条目继续使用 items 的 title/description/kind。不引入 schema 迁移，退役 kind 列不作为展示依据。
- 前台更新页只请求已发布记录，计划留在后台维护；默认展开最近一条，支持按类别及主题、摘要、条目和日期搜索。编辑时间不参与历史排序和功能日期展示。
- 后端写入编排在 `services/product_updates.py`，查询与替换在 repository。日期唯一性在低频写入的表锁内检查，不为本次内容整理增加数据库约束迁移。

## 数据事实源与重建

页面只读数据库，JSON 是一次性整理稿和可审阅的导入来源，不是启动时自动覆盖数据的第二条读取链路。后台后续编辑以数据库为准，重新导入必须显式核对指纹。

重建工具 `backend/scripts/rebuild_release_notes.py` 默认只读计划。写入要求：完整 PostgreSQL 自定义格式备份、当前记录指纹、独立记录快照输出路径；锁表后重新核对指纹，先写出并 fsync 快照，再在同一事务内替换本表。输入规范化后必须无重复日期，空稿和非法条目在删除前拒绝。

回滚通过 `--restore` 恢复快照的完整字段和 ID，也必须核对快照文件指纹及当前数据库指纹，并备份当前状态。仅替换 product_updates，不修改用户反馈、内容、账号或其它业务表。

### 操作入口

在 backend 目录内，先确认 DATABASE_URL 指向预期环境；下面路径由操作者指定，凭据通过环境传递，不写入整理稿。

1. `BACKUP_KEEP_COUNT=0 ./scripts/backup_db.sh <备份目录>`；用 `pg_restore --list <dump>` 检查备份可读。
2. `uv run python scripts/rebuild_release_notes.py` 查看计划与 current_fingerprint。
3. `uv run python scripts/rebuild_release_notes.py --apply --expected-fingerprint <计划指纹> --backup <写入前记录.json> --database-backup <完整dump>`。
4. 需要回滚时，重新只读查询当前指纹，再执行 `uv run python scripts/rebuild_release_notes.py --restore <原记录.json> --expected-fingerprint <当前指纹> --backup <回滚前记录.json> --database-backup <完整dump>`。

## 取舍

不修改历史迁移，不让升级/重启自动重建记录，避免覆盖管理员后来编辑的内容。初装或要采用这套整理稿的环境也显式执行该工具。既有空主题字段允许读出原始空值，新创建和编辑要求完整主题、摘要和日期。

不把依赖升级、CI、格式修复和数据库补录逐条当作用户更新，也不写缺少测量证据的性能百分比或生产稳定性承诺。事件关系相关表述保留审核/启用合同，不宣称自动归并已全面开放。

## 验证边界

测试覆盖内容来源结构、日期规范化、重复日期、主题/摘要写入、未核实上线时间保留、前台筛选排序，以及替换/恢复/指纹冲突/事务回滚。真实画面检查桌面、手机、搜索、折叠与后台编辑。生产数据重建与生产部署需要各自授权，本地数据替换和测试不替代生产验收。
