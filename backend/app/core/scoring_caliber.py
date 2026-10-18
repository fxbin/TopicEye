"""
评分口径唯一真相源(single source of truth)。

历史上同一套精选评分口径分散在三个存储位置各写一份且互相矛盾(#110):

- LLM prompt 教学(app/services/llm/prompts/analysis.py 的中/英/论文三套);
- 引擎 CONFIG(原 scoring_engine.py 顶部字典);
- picks SQL(app/services/_duckdb_picks_mixin.py 的签名默认值)。

本模块是这些数字的唯一声明处:

- ``CONFIG``:引擎与 DuckDB/OLTP 查询的全部可调常数(自 scoring_engine
  迁入,scoring_engine 再导出以兼容既有 ``import CONFIG`` 的引用面);
- ``LLM_RISK_PENALTY_*``:仅存在于 prompt 教学的风险扣分规则,与引擎侧
  ``risk_soft_start``/``risk_threshold`` 软门是两个机制,不混用;
- ``curation_weights_text`` 等三个渲染函数:三套语言 prompt 的口径文本
  从这里生成,prompt 文件不得再手写数字。

漂移防线:tests/test_scoring_caliber.py 用正则从 prompt 成品文本提取
权重/门槛/扣分数字与本模块 CONFIG 断言一致——绕过本模块手改 prompt
数字,CI 即红。
"""

from __future__ import annotations

CONFIG = {
    # 6-dimension weights (must sum to 1.0)
    "w_info_density": 0.25,  # 信息密度
    "w_actionability": 0.20,  # 可操作性
    "w_creator_value": 0.18,  # 创作者价值
    "w_viral_potential": 0.15,  # 爆文潜力
    "w_source_authority": 0.12,  # 来源权威度
    "w_freshness": 0.10,  # 时效新鲜度
    # Source weight mapping (source.weight 1-5 → bonus)
    "source_weight_bonus_factor": 6.0,  # per weight-unit above 3
    # Time decay
    "time_decay_lambda": 0.02,  # decay rate: exp(-lambda * hours)
    "time_decay_floor": 0.3,  # minimum time decay (never fully kill)
    # Content quality gates
    "quality_gate_min": 45,  # below this, content is probably too thin for curation
    "quality_gate_strong": 70,  # full trust above this composite quality level
    "quality_gate_floor": 0.55,  # lowest multiplier for weak-but-not-risky content
    "min_selected_base_score": 58,  # do not select weak items just because a batch is weak
    # Source diversity
    "diversity_penalty_base": 0.85,  # multiplier per same-source duplicate
    "category_diversity_penalty_base": 0.92,
    "same_source_grace": 1,  # first item per source is free
    "same_category_grace": 3,  # first few items per category are free
    # Risk
    "risk_threshold": 82,  # hard-exclude above this
    "risk_soft_start": 45,  # risk starts reducing rank after this
    "risk_soft_floor": 0.55,  # minimum multiplier before hard exclusion
    # Curation threshold (minimum final score to be selected)
    "curation_threshold": 55,  # slightly lower than before, because scores are now more calibrated
    # Fallback: when curation_score is 0 but other scores exist
    "fallback_use_avg": True,
    # ── Percentile-based curation mode ──
    "curation_mode": "percentile",  # "percentile" | "fixed"
    "curation_percentile": 70,  # top ~30% selected (P70 and above) → ~25-30% curation rate
    # ── User feedback signal ──
    "w_feedback": 0.15,  # 15% weight for feedback_score
    "feedback_score_min": -20.0,  # one effective negative vote should not dominate ranking
    "feedback_score_max": 20.0,  # one effective positive vote should not dominate ranking
    # ── picks 查询加成(#110 收编) ──
    # query_today_picks 与 today_picks OLTP fallback 共用的信源权重加成
    # (每单位 source.weight(1-5)高于 3 的加分数),此前在两处各硬编码 8。
    "picks_weight_bonus": 8,
    # ── curation_score 混合比例(#110 收编) ──
    # base = curation_score * p + 六维加权和 * (1 - p),此前硬编码 0.6。
    "curation_blend_weight": 0.6,
}

# ── LLM prompt 教学口径(引擎侧无对应机制,单独声明) ──────────────────
# prompt 教 LLM 组装 curation_score 时的风险扣分规则;引擎侧重用上面的
# risk_soft_start/risk_threshold 软门,二者是不同机制,不互相推导。
LLM_RISK_PENALTY_TRIGGER = 70  # 风险分超过此值
LLM_RISK_PENALTY_POINTS = 20  # 扣除的分数

_WEIGHT_LABELS: dict[str, list[tuple[str, str]]] = {
    "zh": [
        ("w_info_density", "信息密度"),
        ("w_actionability", "可操作性"),
        ("w_creator_value", "创作者价值"),
        ("w_viral_potential", "爆文潜力"),
        ("w_source_authority", "来源"),
        ("w_freshness", "时效"),
    ],
    "en": [
        ("w_info_density", "info density"),
        ("w_actionability", "actionability"),
        ("w_creator_value", "creator value"),
        ("w_viral_potential", "viral potential"),
        ("w_source_authority", "source"),
        ("w_freshness", "timeliness"),
    ],
}


def curation_weights_text(lang: str = "zh") -> str:
    """LLM curation_score 的加权口径文本,数值取自 CONFIG 六维权重。"""
    labels = _WEIGHT_LABELS.get(lang, _WEIGHT_LABELS["zh"])
    sep = "+ " if lang == "en" else "+"
    return sep.join(f"{label}{int(round(CONFIG[key] * 100))}%" for key, label in labels)


def curation_threshold_text(lang: str = "zh") -> str:
    """LLM prompt 的精选门槛句,数值取自 CONFIG curation_threshold。"""
    if lang == "en":
        return f"Curation threshold is {CONFIG['curation_threshold']} points"
    return f"精选门槛为 {CONFIG['curation_threshold']} 分"


def risk_penalty_text(lang: str = "zh") -> str:
    """LLM curation_score 的风险扣分规则句。"""
    if lang == "en":
        return f"risk>{LLM_RISK_PENALTY_TRIGGER} deducts {LLM_RISK_PENALTY_POINTS} points"
    return f"风险分>{LLM_RISK_PENALTY_TRIGGER}则扣{LLM_RISK_PENALTY_POINTS}分"


# ── 六维评分行为锚点(#114,C3 试点) ────────────────────────────────────
# scores 块六维从「一句名称提示」升级为四档可判定行为描述,让打分跨样本、
# 跨语种可比:同一个 85 分在任何一天意味着同一件事。每档写「可判定的行为
# 特征」而非抽象程度词;中文为口径原文,英文为同一标尺译文。
# 论文版 prompt 是否复用属独立决策(#114),首期只挂中/英两套。
ANCHOR_BANDS: tuple[tuple[int, int], ...] = ((0, 30), (40, 60), (70, 85), (90, 100))

DIMENSION_ANCHORS_ZH: dict[str, list[str]] = {
    "quality_score": [
        "纯转发、寒暄或情绪宣泄，信息量趋近于零，或逻辑断裂看不出主线",
        "有明确观点且能自圆其说，但缺少数据、案例或可验证细节",
        "论证完整，带数据/案例/步骤等可验证细节，主线清晰",
        "一手深料：独家数据、完整方法论、系统实测或深度复盘",
    ],
    "hot_score": [
        "无讨论量，发布于冷门角落，看不到互动信号",
        "小圈子在讨论（评论数十量级），尚未出圈",
        "多个社区或账号在转述，评论区活跃，趋势榜可见",
        "刷屏级：热搜头部、多平台同时爆发、大V密集跟进",
    ],
    "freshness_score": [
        "数月前的旧闻，或已被充分报道的旧信息",
        "一周内的动态，或旧话题的新进展",
        "24-72小时内的新发布或首发报道",
        "独家首发、官宣/泄露后数小时、或当天突发",
    ],
    "creator_score": [
        "与目标领域无关，或没有可延展的选题空间",
        "领域相关可作背景素材，但角度已被写烂",
        "能直接展开成一篇内容：角度明确、读者清晰、有差异化空间",
        "选题富矿：可系列化、多角度深挖，或正处话题空白期",
    ],
    "viral_score": [
        "话题封闭，只有当事人与极少数人关心",
        "有一定共鸣点，但表达门槛高，难以通俗转述",
        "有冲突、反常识或实用钩子，一句话能讲清，易被转发",
        "踩中大众情绪点或强实用干货，天然适合标题与二创",
    ],
    "risk_score": [
        "常规技术/产品/资讯内容，无可预见争议",
        "轻度敏感：涉争议人物、营销夸大或立场分歧，需注意措辞",
        "高风险：未证实的重大指控、医疗/投资建议类、平台限流领域",
        "红线：违法、色情、歧视、谣言等，不建议触碰",
    ],
}

DIMENSION_ANCHORS_EN: dict[str, list[str]] = {
    "quality_score": [
        "pure repost, small talk, or venting with near-zero information, or incoherent logic",
        "has a clear, self-consistent viewpoint but lacks data, cases, or verifiable detail",
        "complete argument with data/cases/steps and verifiable detail, clear throughline",
        "first-hand depth: exclusive data, full methodology, systematic hands-on testing, or deep retrospective",
    ],
    "hot_score": [
        "no discussion, posted in an obscure corner, no engagement signals",
        "niche community discussing it (dozens of comments), not yet breaking out",
        "multiple communities/accounts relaying it, active comments, visible on trend boards",
        "explosive: top of trending, erupting across platforms, heavy influencer pickup",
    ],
    "freshness_score": [
        "months-old news, or information already widely covered",
        "a development within the past week, or a new twist on an old topic",
        "new release or first report within 24-72 hours",
        "exclusive debut, hours after announcement/leak, or same-day breaking",
    ],
    "creator_score": [
        "irrelevant to the target domain, or no angle to build on",
        "domain-relevant background material, but the angle is worn out",
        "directly expandable into a piece: clear angle, clear audience, room to differentiate",
        "topic goldmine: series-worthy, multi-angle, or filling a topical blank",
    ],
    "viral_score": [
        "closed topic, only stakeholders and a handful of people care",
        "some resonance, but hard to convey in plain words",
        "conflict/counter-intuitive/practical hook, explainable in one sentence, easy to share",
        "mass emotional appeal or strong utility, naturally title- and remix-friendly",
    ],
    "risk_score": [
        "routine tech/product/news content, no foreseeable controversy",
        "mildly sensitive: controversial figures, marketing hype, or divisive stances",
        "high risk: unverified serious allegations, medical/investment advice, platform-throttled areas",
        "red line: illegal, pornographic, discriminatory, or rumor content",
    ],
}


def dimension_anchor_lines(lang: str = "zh") -> list[str]:
    """六维行为锚点行(每维一行,四档以分号分隔),数值与文案同出本模块。"""
    table = DIMENSION_ANCHORS_EN if lang == "en" else DIMENSION_ANCHORS_ZH
    sep = "; " if lang == "en" else "；"
    colon = ": " if lang == "en" else "："
    lines: list[str] = []
    for dim, descriptions in table.items():
        parts = [f"{lo}-{hi}={descriptions[i]}" for i, (lo, hi) in enumerate(ANCHOR_BANDS)]
        lines.append(f"- {dim}{colon}" + sep.join(parts))
    return lines


def dimension_anchor_section(lang: str = "zh") -> str:
    """prompt 的完整锚点段落(标题行 + 六行锚点),中/英共用同一标尺。"""
    if lang == "en":
        header = "Six-dimension scoring anchors (score by band; interpolate between bands):"
    else:
        header = "六维评分锚点（按档给分，档间取值按程度插值）："
    return header + "\n" + "\n".join(dimension_anchor_lines(lang))
