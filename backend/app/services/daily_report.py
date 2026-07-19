"""
Daily Report service — generate versioned daily snapshots and final editions.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import database_profile
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.daily_report import DailyReport
from app.repositories.content_repo import ContentRepo
from app.repositories.ignored_repo import IgnoredRepo
from app.services.content_serialization import latest_analysis_from_item
from app.services.digest_fallback import build_daily_editorial_fallback
from app.services.llm import call_llm_json
from app.services.scoring_engine import score_items
from app.services.scoring_inputs import build_scoring_inputs
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger(__name__)


WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
VALID_EDITIONS = {"snapshot", "noon", "evening", "final", "manual", "legacy"}
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
GENERATING_STALE_AFTER = timedelta(minutes=10)

# 后端兜底校验常量（不信任 LLM 输出的枚举/字段约束）
_VALID_LIFECYCLE = {"上升期", "见顶", "退潮"}
_BRIEF_ALLOWED_FIELDS = {
    "source_idx", "source_title", "source_title_zh", "editorial_title", "title",
    "tier", "category", "reason", "platforms", "source_url", "score",
}

SYSTEM_PROMPT = """你是 TopicEye 的资深内容主编，为内容创作者编写每日 AI 选题日报。读者是公众号、小红书、视频号的创作者，他们需要"今天写什么、怎么写、为什么值得写"。

## 编辑立场
- 你是"行业观察者"，不是"预言家"。可以有点评和取舍，但不做"必将/彻底改变/颠覆/革命性"这类无证据的因果断言。
- 标题要带编辑判断，必须锚定原文中的核心实体或数字，不得凭空拔高。全篇不得有 2 条 editorial_title 使用相同句式开头。
- 任何 lifecycle 或趋势判断，必须有至少 2 条素材支撑；只有单一信号时，不要下"见顶/退潮"的强判断，在 pitfall 里注明"单一信号，待观察"。

## 防幻觉硬规则
- top_picks 只能从「精选内容」中选。source_idx 必须是精选内容列表里真实存在的序号；source_title 必须逐字复制该序号对应素材的标题原文，不得改写。
- source_title_zh：若 source_title 是英文，给出其中文翻译（产品名/技术术语保留英文原名，如"OpenAI 发布 GPT-5.6"）；若 source_title 本身是中文，填空字符串""。翻译要准确简洁，不加解释。
- editorial_title 是展示用的观点化标题，可以改写，但必须包含原文中的核心实体或关键数字，让读者能对应回原文。
- source_url 字段留空字符串即可，系统会根据 source_idx 自动填入正确链接，你不要自己写 URL。
- overview / reason / angles 中的每个事实，必须能在精选内容或候选背景中找到依据；找不到依据的字段填 null，禁止编造。
- 素材里没有的信息，一律不输出。所有文本用中文，不要输出英文。

## 输出格式
- 只输出一个合法 JSON 对象。不要 markdown 代码围栏，不要任何解释文字。
- 如果精选内容不足 6 条，就少输出 top_picks，不要从候选背景里硬凑。"""


REPORT_PROMPT = """## 日报窗口
- 日期：{date}（{weekday}）
- 版本：{edition_label}
- 统计窗口：{window_start} ~ {window_end}

## 精选内容（top_picks 只能从这里选，序号即 source_idx）
{curated_items_text}

## 候选背景（仅用于判断 overview / trends / keywords 的方向，不能作为 top_picks）
{background_items_text}

## 输出 JSON 结构（严格按此输出，只输出 JSON）
{{
  "overview": "今日主题段，150字内。第一句必须是行动指令，直接告诉创作者'今天最值得写什么'（必须含当天至少1个具体实体名或数字）；第二句给论点判断——从下列句式中选一个，不要每次都用同一个：(a)'当……时，首先要解决的不是……，而是……' (b)'这些信号合在一起，指向一个反直觉的结论：……' (c)'表面上看是……，真正的机会在……' (d)'……这件事，比看上去更值得做（或更危险），原因是……'；第三句用'从 X、Y 切入，分别看 A、B'把精讲选题映射到维度。禁止'今天有N篇报道'开头，禁止罗列关键词，必须兼顾机会与风险。",
  "takeaway": "适合做推送标题的一句话，20字内，必须带一个冲突或一个数字，禁止'XX成新焦点''XX时代来了'这类万能句式",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "trends": [
    {{"title": "趋势标题", "desc": "趋势描述（30字内）", "color": "#3B82F6", "momentum": "up"}}
  ],
  "top_picks": [
    {{
      "source_idx": 1,
      "source_title": "逐字复制精选内容中序号1的标题原文",
      "source_title_zh": "英文标题的中文翻译；中文标题填空字符串",
      "editorial_title": "观点化展示标题",
      "tier": "feature",
      "category": "模型发布",
      "reason": "中文摘要式推荐理由，两段式：先概括这条内容讲了什么，再说明为什么值得写。feature 80字内，brief 40字内",
      "angles": ["动宾短语，描述能做成什么内容，≤15字，禁问句"],
      "pitfall": "避坑提示（时效/争议/信息不足），无依据时填 null",
      "lifecycle": "上升期",
      "time_window": "发布时间建议，如'建议48h内发布'",
      "platforms": ["公众号", "小红书"],
      "source_url": ""
    }},
    {{
      "source_idx": 5,
      "source_title": "逐字复制精选内容中序号5的标题原文",
      "source_title_zh": "英文标题的中文翻译；中文标题填空字符串",
      "editorial_title": "速览标题：一句话事实+价值点",
      "tier": "brief",
      "category": "产品更新",
      "reason": "一句话说明为什么值得扫一眼，40字内",
      "platforms": ["公众号"],
      "source_url": ""
    }}
  ],
  "platform_tips": {{
    "公众号": ["今日面向公众号的创作建议"],
    "小红书": ["今日面向小红书的创作建议"],
    "视频号": ["今日面向视频号的创作建议"]
  }}
}}

## 选题分层规则（重要）
- top_picks 共 6-9 条。按"可写性"分层（不是按 overview 主线）：
  - tier="feature" 2-3 条：精选分最高的、最有实操空间的选题。必须给全 reason/angles/pitfall/lifecycle/time_window/platforms。
  - tier="brief" 4-6 条：其余值得关注但不展开的。允许字段仅 source_idx/source_title/editorial_title/tier/category/reason/platforms/source_url。禁止出现 lifecycle、time_window、angles、pitfall 字段（哪怕值为空或"?"也不行）。
- 排序：feature 在前（精选分降序），brief 在后（精选分降序）。

## angles 写作规范（核心）
- angles 必须是名词短语或动宾短语，描述"能做成什么内容"，≤15字，禁止问句。
- 正例：MCP实操教程 | 拆解Claude的token计费 | 测评5款开源Agent框架 | 用Coze复刻XX工作流 | 扒5个判例看巨头挖角史
- 负例（禁止）：大厂能多霸道？ | AI真的能取代编辑吗？ | 你会用MCP吗？
- 每条 feature 给 2-3 个 angles，切入主体要差异化（如换主角视角/换时间尺度/换输出形态各一）。

## editorial_title 写作规范
- 必须含原文核心实体（让读者能对应回原文），但与 source_title 的字面重合度 < 50%。
- 从下列结构中选一个（全篇不得 2 条用相同结构）：
  (a) "别再用 X 做 Y" + 立场（如：别再用BLEU评估中文模型）
  (b) "X 的真正问题不是 A，是 B"
  (c) "把 X 拆开看：A 比 B 更值得抄"
  (d) "X 这一步，决定了 Y 的天花板"
- 反例（太接近搬运，禁止）：source="Siri升级为系统核心，公测开启" → editorial="Siri升级背后：系统核心之争"
- 正例：source 同上 → editorial="Siri想当系统大脑，得先过开发者信任这一关"
- 禁止感叹号堆叠和"震惊/必看/重磅"类词。

## 其他写作规范
- category 从"模型发布""产品更新""行业动态""技巧观点""科研论文""开源项目"中选最贴近的一个。
- trends.momentum 从"up""down""stable"三选一，给出 2-3 个今日内容趋势。
- lifecycle 仅限三选一："上升期" | "见顶" | "退潮"。不得输出"爆发期/萌芽期/成长期/衰退期/发酵期"等同义词。仅 feature 需要此字段。
- reason 必须是中文摘要式推荐理由：先概括这条内容讲了什么，再说明为什么值得写；不要输出英文、不要营销夸张词、不要只写"建议关注/可以写"。
- 如果精选内容较少，就少选，不要从候选背景中硬凑。
- 只输出 JSON，不要其他内容"""


def _local_now() -> datetime:
    return datetime.now(LOCAL_TZ).replace(tzinfo=None, microsecond=0)


def _local_today() -> date:
    return _local_now().date()


def _as_local_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(microsecond=0)
    return value.astimezone(LOCAL_TZ).replace(tzinfo=None, microsecond=0)


def _local_window_to_utc_naive(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Convert local report-display window to storage/query window."""
    return (
        start.replace(tzinfo=LOCAL_TZ).astimezone(UTC).replace(tzinfo=None),
        end.replace(tzinfo=LOCAL_TZ).astimezone(UTC).replace(tzinfo=None),
    )


def _day_window(target: date, cutoff_at: datetime | None, edition: str) -> tuple[datetime, datetime]:
    start = datetime.combine(target, time.min)
    if edition == "final":
        return start, datetime.combine(target, time.max).replace(microsecond=0)

    if cutoff_at is None:
        cutoff_at = _local_now()
    cutoff_at = _as_local_naive(cutoff_at)
    # A same-day snapshot is always bounded to that date.
    end = min(cutoff_at.replace(microsecond=0), datetime.combine(target, time.max).replace(microsecond=0))
    if end < start:
        end = datetime.combine(target, time.max).replace(microsecond=0)
    return start, end


def _edition_for_now(now: datetime | None = None) -> str:
    now = _as_local_naive(now) or _local_now()
    if now.hour < 14:
        return "noon"
    if now.hour < 22:
        return "evening"
    return "snapshot"


def _edition_label(edition: str) -> str:
    return {
        "noon": "午间快照",
        "evening": "晚间快照",
        "final": "完整复盘",
        "manual": "手动快照",
        "snapshot": "实时快照",
        "legacy": "历史日报",
    }.get(edition, edition)


def _normalize_edition(edition: str | None, target: date, cutoff_at: datetime | None) -> str:
    if edition:
        normalized = edition.lower()
        if normalized not in VALID_EDITIONS:
            raise ValueError(f"Unsupported daily report edition: {edition}")
        return normalized

    today = _local_today()
    if target < today:
        return "final"
    return _edition_for_now(cutoff_at)


def _is_active_generating(report: DailyReport, now: datetime) -> bool:
    if report.status != "GENERATING":
        return False
    generated_at = _as_local_naive(report.generated_at) or _as_local_naive(report.updated_at) or now
    return now - generated_at < GENERATING_STALE_AFTER


async def _fetch_report_inputs(
    db: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    visible_user_id: int | None = None,
) -> tuple[list[dict], list[dict]]:
    repo = ContentRepo(db)
    query_start, query_end = _local_window_to_utc_naive(window_start, window_end)
    ignored_ids = await IgnoredRepo(db).list_ignored_ids()
    items = list(
        await repo.list_for_report_window(
            window_start=query_start,
            window_end=query_end,
            visible_user_id=visible_user_id,
            exclude_ids=ignored_ids,
        )
    )
    scoring_inputs, item_map, _ = await build_scoring_inputs(db, items)
    scored = score_items(scoring_inputs) if scoring_inputs else []

    curated: list[dict] = []
    for breakdown, si in scored:
        item = item_map.get(si.content_id)
        if not item:
            continue
        analysis = latest_analysis_from_item(item)
        if analysis is None:
            continue
        record = _item_to_report_dict(item, analysis, breakdown.final_score)
        if breakdown.selected:
            curated.append(record)

    # If the window is sparse, still provide a few high-quality analyzed items as context,
    # but top_picks will be instructed to use only selected curated items.
    background = [
        _item_to_report_dict(item, analysis, analysis.curation_score or 0)
        for item in items
        if (analysis := latest_analysis_from_item(item)) is not None
    ]
    background.sort(key=lambda x: (x["curation_score"], x["creator_score"]), reverse=True)
    curated.sort(key=lambda x: (x["adjusted_score"], x["curation_score"]), reverse=True)
    return curated, background


def _item_to_report_dict(item, analysis, adjusted_score: float) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "url": normalize_zhihu_url(item.url),
        "category": item.category or "未分类",
        "source_name": item.source_name or "",
        "creator_score": analysis.creator_score or 0,
        "viral_score": analysis.viral_score or 0,
        "quality_score": analysis.quality_score or 0,
        "risk_score": analysis.risk_score or 0,
        "curation_score": analysis.curation_score or 0,
        "adjusted_score": round(float(adjusted_score or 0), 1),
        "summary": analysis.summary or item.summary or "",
        "recommendation": analysis.recommendation or analysis.recommended_reason or "",
    }


def _format_items(items: list[dict], *, limit: int, selected: bool) -> str:
    if not items:
        return "暂无"

    lines: list[str] = []
    for idx, item in enumerate(items[:limit], 1):
        score = item.get("adjusted_score") if selected else item.get("curation_score")
        # 序号即 source_idx，模型按序号回引；URL 不喂给模型（由后端按 idx 注入，避免改写）。
        lines.append(f"\n{idx}. [{item['category']}] {item['title']}")
        lines.append(
            "   "
            f"来源: {item['source_name']} | "
            f"精选:{score:.1f} 创作:{item['creator_score']:.1f} "
            f"爆文:{item['viral_score']:.1f} 质量:{item['quality_score']:.1f} 风险:{item['risk_score']:.1f}"
        )
        if item.get("recommendation"):
            lines.append(f"   推荐: {str(item['recommendation'])[:150]}")
        if item.get("summary"):
            lines.append(f"   摘要: {str(item['summary'])[:200]}")
    return "\n".join(lines)


async def get_latest_today_report(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
) -> DailyReport:
    """Return today's newest report, generating a snapshot if none exists.

    ``owner_user_id``: ``None`` → public (NULL) report; ``int`` → strictly the
    user's own report. Pass the user's id for the /me endpoints.
    """
    today = _local_today().isoformat()
    result = await db.execute(
        select(DailyReport)
        .where(DailyReport.report_date == today)
        .where(DailyReport.owner_user_id.is_(owner_user_id))
        .order_by(DailyReport.cutoff_at.desc(), DailyReport.updated_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if report:
        return report
    return await generate_daily_report(
        db,
        target_date=_local_today(),
        edition=_edition_for_now(),
        owner_user_id=owner_user_id,
    )


async def generate_daily_report(
    db: AsyncSession,
    *,
    target_date: date | None = None,
    edition: str | None = None,
    cutoff_at: datetime | None = None,
    force: bool = False,
    owner_user_id: int | None = None,
) -> DailyReport:
    """Generate a versioned daily report for a precise time window.

    ``owner_user_id``: ``None`` → public report; ``int`` → user-owned report.
    Pass the user's id for the /me endpoints.
    """
    target = target_date or _local_today()
    normalized_edition = _normalize_edition(edition, target, cutoff_at)
    window_start, window_end = _day_window(target, cutoff_at, normalized_edition)
    report_date = target.isoformat()
    weekday = WEEKDAYS[target.weekday()]
    now = _local_now()

    async def _claim_generation() -> tuple[DailyReport, bool]:
        if database_profile.is_sqlite:
            await begin_immediate_for_sqlite(db)

        existing_stmt = (
            select(DailyReport)
            .where(DailyReport.report_date == report_date)
            .where(DailyReport.edition == normalized_edition)
            .where(DailyReport.cutoff_at == window_end)
            .where(DailyReport.owner_user_id.is_(owner_user_id))
        )
        if database_profile.is_postgresql:
            existing_stmt = existing_stmt.with_for_update()

        existing = await db.execute(existing_stmt)
        report = existing.scalar_one_or_none()
        if report and report.status == "DONE" and not force:
            return report, False
        if report and _is_active_generating(report, now) and not force:
            return report, False

        if not report:
            report = DailyReport(
                report_date=report_date,
                weekday=weekday,
                edition=normalized_edition,
                generated_at=now,
                window_start=window_start,
                window_end=window_end,
                cutoff_at=window_end,
                source_scope="curated",
                status="GENERATING",
                content_count=0,
                analyzed_count=0,
                owner_user_id=owner_user_id,
            )
            db.add(report)
            try:
                await db.flush()
            except IntegrityError:
                await db.rollback()
                existing = await db.execute(
                    existing_stmt.with_for_update() if database_profile.is_postgresql else existing_stmt
                )
                report = existing.scalar_one()
                if report.status == "DONE" and not force:
                    return report, False
                if _is_active_generating(report, _local_now()) and not force:
                    return report, False
                report.status = "GENERATING"
                report.generated_at = _local_now()
                await db.flush()
        else:
            report.status = "GENERATING"
            report.generated_at = now
            report.window_start = window_start
            report.window_end = window_end
            report.cutoff_at = window_end
            await db.flush()

        return report, True

    report, claimed = await retry_sqlite_locked(
        _claim_generation,
        attempts=4,
        base_delay=0.1,
        on_retry=db.rollback,
    )
    if not claimed:
        return report

    await db.commit()

    curated_items, background_items = await _fetch_report_inputs(
        db,
        window_start=window_start,
        window_end=window_end,
        visible_user_id=owner_user_id,
    )
    report.content_count = len(background_items)
    report.analyzed_count = len(background_items)
    await db.flush()

    if not background_items:
        report.status = "ERROR"
        report.overview = "当前窗口暂无分析数据，请先同步信源并等待 AI 分析完成。"
        report.source_item_ids = json.dumps([], ensure_ascii=False)
        await db.commit()
        return report

    # 日报的可推荐选题只能来自精选池。背景素材只用于帮助归纳当天脉络，
    # 不能在精选为空时补位成日报推荐；否则会让“日报精选”的边界失真。
    if not curated_items:
        report.status = "DONE"
        report.overview = "今日暂未形成可推荐精选。已分析素材会继续参与后续评分，达到精选门槛后再进入日报。"
        report.takeaway = "今日暂无达到精选门槛的选题"
        report.keywords = json.dumps([], ensure_ascii=False)
        report.trends = json.dumps([], ensure_ascii=False)
        report.top_picks = json.dumps([], ensure_ascii=False)
        report.platform_tips = json.dumps({}, ensure_ascii=False)
        report.topic_count = 0
        report.source_item_ids = json.dumps([], ensure_ascii=False)
        report.updated_at = _local_now()
        await db.commit()
        return report

    # 截断一次：prompt 展示列表与下方匹配逻辑共用同一份，保证 source_idx 一致。
    curated_for_prompt = curated_items[:50]
    curated_text = _format_items(curated_for_prompt, limit=50, selected=True)
    background_text = _format_items(background_items, limit=80, selected=False)

    prompt = REPORT_PROMPT.format(
        date=report_date,
        weekday=weekday,
        edition_label=_edition_label(normalized_edition),
        window_start=window_start.strftime("%Y-%m-%d %H:%M"),
        window_end=window_end.strftime("%Y-%m-%d %H:%M"),
        curated_items_text=curated_text,
        background_items_text=background_text,
    )

    try:
        result = await call_llm_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            scene="daily_report",
            temperature=0.4,
            max_tokens=4000,
        )
        overview = result.get("overview", "")
        if not overview or "raw_response" in result:
            result = build_daily_editorial_fallback(
                curated_items,
                label=f"{report_date} {_edition_label(normalized_edition)}",
            )
            overview = result.get("overview", "")

        report.overview = overview
        report.takeaway = result.get("takeaway", "")
        report.keywords = json.dumps(result.get("keywords", []), ensure_ascii=False)
        report.trends = json.dumps(result.get("trends", []), ensure_ascii=False)

        raw_picks = result.get("top_picks", [])
        picks = []
        # source_idx 主匹配（精确），source_title 子串兜底，URL 末位兜底。
        matchable_items = curated_for_prompt
        curated_by_idx = {i + 1: item for i, item in enumerate(matchable_items)}
        curated_by_title = {item["title"]: item for item in matchable_items}
        curated_by_url = {
            normalize_zhihu_url(item.get("url", "")): item for item in matchable_items if item.get("url")
        }
        curated_titles = set(curated_by_title)
        selected_source_ids: list[int] = []
        for pick in raw_picks:
            matched_item: dict | None = None
            idx = pick.get("source_idx")
            if isinstance(idx, int):
                matched_item = curated_by_idx.get(idx)
            if not matched_item:
                source_title = pick.get("source_title", "")
                matched_title = next(
                    (t for t in curated_titles if source_title and (source_title in t or t in source_title)),
                    None,
                )
                matched_item = curated_by_title.get(matched_title) if matched_title else None
            if not matched_item:
                pick_url_norm = normalize_zhihu_url(pick.get("source_url", ""))
                matched_item = curated_by_url.get(pick_url_norm)
            if not matched_item:
                continue
            # 注入稳定字段：URL/title/score 由后端按匹配结果填，模型无需也不应改写。
            pick["source_url"] = normalize_zhihu_url(matched_item.get("url", ""))
            pick["source_title"] = pick.get("source_title") or matched_item["title"]
            pick["title"] = pick.get("editorial_title") or matched_item["title"]
            pick["score"] = round(float(matched_item.get("adjusted_score") or matched_item.get("curation_score") or 0))
            # —— 后端兜底校验（不信任 LLM 输出的枚举/字段约束）——
            tier = pick.get("tier") or "feature"
            pick["tier"] = tier
            if tier == "brief":
                # brief 字段白名单：过滤掉 LLM 残留的 feature 专属字段
                pick = {k: v for k, v in pick.items() if k in _BRIEF_ALLOWED_FIELDS}
            else:
                # feature：生命周期没有足够依据时宁可不显示，也不伪造“上升期”。
                lc = pick.get("lifecycle")
                if lc in _VALID_LIFECYCLE:
                    pick["lifecycle"] = lc
                else:
                    pick.pop("lifecycle", None)
                # angles 过滤问句 + 限 3 条
                angles = pick.get("angles") or []
                pick["angles"] = [
                    a for a in angles if isinstance(a, str) and not a.strip().endswith(("？", "?"))
                ][:3]
            picks.append(pick)
            if matched_item["id"] not in selected_source_ids:
                selected_source_ids.append(matched_item["id"])

        report.top_picks = json.dumps(picks, ensure_ascii=False)
        report.platform_tips = json.dumps(result.get("platform_tips", {}), ensure_ascii=False)
        report.topic_count = len(picks)
        report.source_item_ids = json.dumps(
            selected_source_ids or [item["id"] for item in curated_items], ensure_ascii=False
        )
        report.status = "DONE"
        report.updated_at = _local_now()
        await db.commit()
        try:
            from app.services.notification_service import push_notification

            await push_notification(
                "success",
                "daily_report",
                "日报生成完成",
                f"{report_date} {_edition_label(normalized_edition)}，共 {report.topic_count} 个选题",
            )
        except Exception:
            logger.warning("daily_report success notification failed", exc_info=True)

        # webhook 卡片推送（失败不阻塞日报生成）
        try:
            from app.services.alerting import send_alert

            # 构造卡片内容：overview 摘要 + top 3 picks
            overview_text = (report.overview or "")[:200]
            top3_lines: list[str] = []
            for i, pick in enumerate(picks[:3], start=1):
                title = pick.get("editorial_title") or pick.get("source_title") or f"选题 {i}"
                tier = pick.get("tier", "")
                tier_tag = f" `[{tier}]`" if tier else ""
                top3_lines.append(f"**{i}. {title}**{tier_tag}")

            card_content_parts = [overview_text]
            if top3_lines:
                card_content_parts.append("\n---\n**今日精选 Top 3：**\n" + "\n".join(top3_lines))
            if report.topic_count > 3:
                card_content_parts.append(f"\n…共 {report.topic_count} 个选题")

            card_content = "\n".join(card_content_parts)
            card_link = f"/daily?date={report_date}"

            await send_alert(
                title=f"📰 AI 日报 · {report_date} {_edition_label(normalized_edition)}",
                message=f"日报生成完成，共 {report.topic_count} 个选题",
                alert_key=f"daily_report:{report_date}:{normalized_edition}",
                severity="info",
                event_type="daily_report",
                card={"content": card_content, "link": card_link},
            )
        except Exception:
            logger.warning("daily_report webhook push failed (non-fatal)", exc_info=True)
    except Exception as exc:
        report.status = "ERROR"
        report.overview = f"生成失败: {str(exc)[:200]}"
        report.source_item_ids = json.dumps([item["id"] for item in curated_items], ensure_ascii=False)
        await db.commit()
        try:
            from app.services.notification_service import push_notification

            await push_notification("error", "daily_report", "日报生成失败", str(exc)[:200])
        except Exception:
            logger.warning("daily_report failure notification failed", exc_info=True)

    return report


async def generate_previous_day_final_report(
    db: AsyncSession,
    *,
    force: bool = False,
    owner_user_id: int | None = None,
) -> DailyReport:
    """Generate yesterday's final full-day edition."""
    yesterday = _local_today() - timedelta(days=1)
    return await generate_daily_report(
        db,
        target_date=yesterday,
        edition="final",
        force=force,
        owner_user_id=owner_user_id,
    )
