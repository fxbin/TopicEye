"""按内容形态解释证据、质量与使用价值；不定义权重，也不在本地猜测模型分数。

中英文本按字段成对维护，四档边界复用 scoring_caliber.ANCHOR_BANDS。
只渲染受信规则，未知 content_type 不插进系统消息。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.content_types import normalize_content_type
from app.core.scoring_caliber import ANCHOR_BANDS

RUBRIC_VERSION = "content-type-v1"
Bilingual = tuple[str, str]
Bands = tuple[Bilingual, Bilingual, Bilingual, Bilingual]


@dataclass(frozen=True)
class ContentTypeRubric:
    label: Bilingual
    quality: Bands
    density: Bilingual
    actionability: Bands
    creator: Bilingual
    caution: Bilingual


# quality 是证据支撑与完整性，info_density 是有效信息占比；两者不联动赋同分。
CONTENT_TYPE_RUBRICS: dict[str, ContentTypeRubric] = {
    "资讯": ContentTypeRubric(
        ("资讯", "News"),
        (
            ("只有传闻、转述标题或无出处断言", "Rumor, a relayed headline, or an unattributed claim only"),
            (
                "事件与出处明确，但关键事实或前后变化缺失",
                "Identifiable event and attribution, but key facts or changes are missing",
            ),
            (
                "新事实可回查，主体、时间、变化和影响对象清楚",
                "Traceable new facts with clear actors, timing, changes, and affected parties",
            ),
            (
                "关键原始材料完整，多方证据解释变化、影响边界与不确定性",
                "Complete primary material and corroboration explain the change, impact boundaries, and uncertainty",
            ),
        ),
        (
            "看新增且可验证的事实占比；短快讯也可高密度，转述堆积不算新增",
            "Assess the share of new verifiable facts; a short bulletin can be dense, repeated retellings add no information",
        ),
        (
            ("不知道发生了什么，也无法据此判断", "Cannot identify what happened or use it for a decision"),
            ("知道有事件，但不知道影响谁或该关注什么", "Identifies an event but not who is affected or what to watch"),
            (
                "明确谁受影响、发生何种变化，可决定是否跟进或写作",
                "Shows who is affected and what changed, supporting a follow-up or editorial decision",
            ),
            (
                "变化及适用边界清楚，给出有依据的跟进节点或比较线索",
                "Clear change and applicability, with evidence-backed follow-up milestones or comparisons",
            ),
        ),
        (
            "看新增事实能否支持有差异的解释或跟进，不因没有操作步骤扣分",
            "Look for differentiated explanations or follow-ups enabled by new facts; do not penalize missing how-to steps",
        ),
        (
            "官宣只证明发布方如此声明；融资、估值不等于利润，未经证实的影响不写成事实",
            "An announcement proves what its issuer claims; funding or valuation is not profit, and unverified impact is not fact",
        ),
    ),
    "教程": ContentTypeRubric(
        ("教程", "Tutorial"),
        (
            ("只承诺效果，没有步骤或关键条件", "Promises outcomes without steps or prerequisites"),
            (
                "有步骤，但缺环境、输入输出或关键环节",
                "Has steps but omits environment, inputs, outputs, or critical transitions",
            ),
            (
                "前提、步骤和预期结果完整，有可核对的示例",
                "Complete prerequisites, steps, and expected outcomes with checkable examples",
            ),
            (
                "完整可复现，并验证失败分支、版本差异及适用边界",
                "Reproducible end to end, validating failure cases, version differences, and applicability",
            ),
        ),
        (
            "看必要步骤、示例、排错信息占比，不按篇幅或代码行数加分",
            "Assess useful steps, examples, and troubleshooting, not length or lines of code",
        ),
        (
            ("无法按文执行", "Cannot execute from the text"),
            ("可尝试但需自行补关键步骤", "Can attempt it, but must invent missing critical steps"),
            ("按文可完成任务并检查结果", "Can finish the task and verify the outcome from the text"),
            (
                "可重复完成，能排错、撤销并判断何时不适用",
                "Repeatably usable, with troubleshooting, undo, and clear limits",
            ),
        ),
        (
            "看是否解决具体读者任务，以及方法有何独特之处",
            "Assess the specific reader task solved and what distinguishes the method",
        ),
        (
            "未实际验证的步骤不能说成作者已实测；高风险操作须有必要防护",
            "Do not present unverified steps as hands-on validation; risky operations need necessary safeguards",
        ),
    ),
    "观点": ContentTypeRubric(
        ("观点", "Opinion / analysis"),
        (
            ("只有情绪、口号或无依据结论", "Emotion, slogans, or unsupported conclusions only"),
            (
                "观点清楚且自洽，但证据薄弱或忽略反例",
                "Clear and coherent position, but weak evidence or ignored counterexamples",
            ),
            (
                "论据可核对，推理完整，区分事实、推测与价值判断",
                "Checkable evidence and complete reasoning distinguish fact, inference, and value judgment",
            ),
            (
                "提出独到解释，检验替代解释与反例，交代结论边界",
                "Original explanation tests alternatives and counterexamples and states its limits",
            ),
        ),
        (
            "看有效论点和证据，重复立场、术语堆砌不算信息",
            "Count substantive arguments and evidence, not repeated positions or jargon",
        ),
        (
            ("无法帮助理解或判断", "Does not support understanding or judgment"),
            ("提供一个视角，但缺判断条件", "Offers a perspective without decision conditions"),
            (
                "给出有依据的解释框架，可帮助读者比较和判断",
                "An evidence-backed explanatory framework supports comparison and judgment",
            ),
            (
                "框架适用条件与反例清楚，可迁移检验而非仅接受立场",
                "Clear conditions and counterexamples make the framework transferable and testable",
            ),
        ),
        (
            "看新解释、争论焦点和可延展角度，不以情绪激烈代替创作价值",
            "Assess new explanations, meaningful disagreements, and extensible angles, not emotional intensity",
        ),
        (
            "相关不等于因果；有争议的观点须保留归属和反方证据",
            "Correlation is not causation; contested views need attribution and opposing evidence",
        ),
    ),
    "工具": ContentTypeRubric(
        ("工具", "Tool / product release"),
        (
            ("只有宣传口号，功能和入口不明", "Marketing slogans with no clear functionality or access"),
            ("说明功能，但缺使用条件、版本或限制", "Describes features but omits conditions, version, or limits"),
            (
                "具体变化、使用场景、入口及成本限制有可回查依据",
                "Traceable changes, use cases, access, costs, and limits",
            ),
            (
                "完整说明能力边界、替代方案及可验证的采用条件",
                "Complete capability boundaries, alternatives, and verifiable adoption conditions",
            ),
        ),
        (
            "看具体功能差异、接入条件和限制，宣传形容词不计入",
            "Assess concrete feature changes, access conditions, and limits, excluding promotional adjectives",
        ),
        (
            ("不知道工具做什么或如何获取", "Unclear purpose or access"),
            ("知道用途，但缺采用所需条件", "Understands the purpose, but lacks adoption conditions"),
            ("能判断是否适合，并找到试用入口及必要条件", "Can assess fit and locate access and prerequisites"),
            (
                "有足够成本、权限、兼容与替代信息支持试用或采用决策",
                "Costs, permissions, compatibility, and alternatives support a trial or adoption decision",
            ),
        ),
        (
            "看解决的任务、新旧差异与读者价值；发布介绍不强制伪装成评测",
            "Assess tasks solved, changes, and reader value; a release description need not pretend to be a review",
        ),
        (
            "发布方的性能声明不等于独立实测；标明版本、付费和不可用条件",
            "Issuer performance claims are not independent tests; keep version, payment, and access limits explicit",
        ),
    ),
    "体验": ContentTypeRubric(
        ("体验", "Hands-on review"),
        (
            ("结论空泛，看不出实际使用", "Vague verdict with no visible hands-on use"),
            ("有使用描述，但缺任务、条件或结果", "Describes usage but lacks tasks, conditions, or results"),
            (
                "交代版本、任务、使用条件与实际结果，优缺点有例证",
                "States version, tasks, conditions, and actual results with evidenced pros and cons",
            ),
            (
                "同条件对照、重复观察和失败案例完整，结论不过度外推",
                "Comparable controls, repeated observations, and failure cases with bounded conclusions",
            ),
        ),
        (
            "看真实观察、对照与问题占比，感受重复和参数抄写不算实测",
            "Assess actual observations, comparisons, and issues; repeated impressions or copied specifications are not tests",
        ),
        (
            ("不能支持使用或购买判断", "Cannot support a usage or purchase decision"),
            ("有个人感受，但难判断是否适合自己", "Personal impressions without enough context to assess fit"),
            ("适用人群、优缺点与成本清楚，可判断是否试用", "Audience, tradeoffs, and costs support a trial decision"),
            (
                "对照条件、替代方案和局限完整，可据此复查并选择",
                "Controls, alternatives, and limits support rechecking and choosing",
            ),
        ),
        (
            "看实测发现能否构成具体比较、避坑或使用建议",
            "Assess whether observations support specific comparisons, pitfalls, or usage advice",
        ),
        (
            "不能把单次体验外推所有用户；区分赞助、作者自述与独立验证",
            "Do not generalize one experience to all users; distinguish sponsorship, author reports, and independent validation",
        ),
    ),
    "论文": ContentTypeRubric(
        ("论文", "Research paper"),
        (
            (
                "研究问题与贡献不明，结论缺必要论证",
                "Unclear research question or contribution, conclusions lack necessary support",
            ),
            (
                "问题和方法清楚，但验证、推导或关键条件不足",
                "Clear question and method, but incomplete validation, derivation, or conditions",
            ),
            (
                "方法、实验或证明支撑主要结论，基线和局限清楚",
                "Methods, experiments or proofs support the main conclusions with clear baselines and limits",
            ),
            (
                "重要新贡献，经严谨实验或完整证明检验，并讨论适用边界",
                "Important new contribution tested by rigorous experiments or complete proofs with clear applicability",
            ),
        ),
        (
            "看问题、方法、结果及证据含量；摘要不足以证明全文严谨，纯理论可用完整证明而非强求实验",
            "Assess question, method, results, and evidence; an abstract cannot establish full-paper rigor, and theoretical work may use proofs rather than experiments",
        ),
        (
            ("无法识别方法用途或认知贡献", "Cannot identify a use or conceptual contribution"),
            (
                "有潜在价值，但缺应用条件或可检验推导",
                "Potential value without application conditions or checkable derivation",
            ),
            (
                "方法可复现，或理论可检验并能支持具体研究判断",
                "Reproducible method, or checkable theory supporting a specific research judgment",
            ),
            (
                "复现材料与适用条件完整，或完整证明可支持明确的新研究路径",
                "Complete replication material and conditions, or complete proofs supporting a concrete new research path",
            ),
        ),
        (
            "看实际贡献、可解释性与选题空间，区分精读价值和普通精选价值",
            "Assess actual contribution, explainability, and editorial potential; distinguish deep-reading value from curation value",
        ),
        (
            "预印本不冒充同行评审；机构名气不证明结果可靠，摘要未给的实验不能补造",
            "A preprint is not peer reviewed; prestige does not prove reliability, and missing experiments must not be invented",
        ),
    ),
    "技术": ContentTypeRubric(
        ("技术", "Technical / engineering"),
        (
            ("堆术语或只给架构结论，没有技术依据", "Jargon or architectural verdicts without technical support"),
            (
                "方案清楚，但缺约束、实现细节或验证",
                "Clear design without constraints, implementation details, or validation",
            ),
            (
                "问题、约束、实现和取舍完整，有数据或案例验证",
                "Complete problem, constraints, implementation, and tradeoffs validated by data or cases",
            ),
            (
                "系统验证性能、可靠性与失败边界，解释替代方案和迁移代价",
                "Systematic performance, reliability, and failure-boundary validation, explaining alternatives and migration costs",
            ),
        ),
        (
            "看可核对的技术机制、取舍与结果，不因复杂术语多而加分",
            "Assess checkable mechanisms, tradeoffs, and results, not jargon complexity",
        ),
        (
            ("无法理解方案解决什么问题", "Cannot tell what problem the design solves"),
            ("可作背景，但缺适用条件", "Useful background without applicability conditions"),
            ("条件与取舍清楚，可指导相似技术选择", "Clear conditions and tradeoffs guide comparable technical choices"),
            (
                "验证与迁移信息完整，可评估落地、失败处置和成本",
                "Validation and migration details support adoption, failure handling, and cost assessment",
            ),
        ),
        (
            "看可讲清的机制与工程经验，不要求技术分析都写成逐步教程",
            "Assess explainable mechanisms and engineering lessons; technical analysis need not be a step-by-step tutorial",
        ),
        (
            "局部测试不代表生产可靠；保留负载、环境、版本和安全前提",
            "Local tests do not establish production reliability; keep load, environment, version, and security assumptions",
        ),
    ),
    "成长": ContentTypeRubric(
        ("成长", "Personal growth / learning"),
        (
            ("鸡汤、成功口号或无依据的普遍承诺", "Motivational slogans or unsupported universal promises"),
            ("方法明确，但只有泛例或个人结论", "Clear method with generic examples or personal conclusions only"),
            (
                "具体情境、做法、结果和限制清楚，有可检查案例",
                "Specific context, actions, outcomes, and limits with checkable cases",
            ),
            (
                "长期记录或多情境验证，含失败、代价和适用差异",
                "Longitudinal or multi-context evidence includes failures, costs, and applicability differences",
            ),
        ),
        (
            "看具体方法和经验事实，重复激励不计入信息密度",
            "Assess concrete methods and experiential facts, excluding repeated encouragement",
        ),
        (
            ("只有激励，没有可尝试的方法", "Encouragement without a method to try"),
            ("有建议，但缺情境或反馈标准", "Advice without context or feedback criteria"),
            ("能在明确情境尝试，并观察结果", "Can try it in a defined context and observe outcomes"),
            (
                "能持续检验、调整与停止，成本和不适用人群清楚",
                "Supports ongoing checking, adjustment, and stopping with clear costs and exclusions",
            ),
        ),
        (
            "看具体读者问题和可讲述经验，不以成功叙事代替证据",
            "Assess specific reader problems and usable experience, not success narratives alone",
        ),
        (
            "个人成功不等于普适因果；心理、健康和财务建议仍受风险约束",
            "Personal success is not universal causality; psychological, health, and financial advice remains subject to risk rules",
        ),
    ),
    "讨论": ContentTypeRubric(
        ("讨论", "Discussion / Q&A"),
        (
            ("互骂、复读或无事实的情绪", "Abuse, repetition, or emotion without facts"),
            ("问题和立场清楚，但缺实际论据", "Clear question and positions without substantive evidence"),
            (
                "多个实质观点有案例或依据，能识别共识与分歧",
                "Substantive positions backed by cases or evidence identify agreement and disagreement",
            ),
            (
                "形成可核对的新发现，处理反例并明确未解决问题",
                "Checkable new findings address counterexamples and identify unresolved issues",
            ),
        ),
        (
            "看有效论点、案例和回答，不按评论数量当质量",
            "Assess substantive arguments, cases, and answers; comment volume is not quality",
        ),
        (
            ("没有可用回答或判断线索", "No usable answer or decision signal"),
            ("暴露问题，但没有可跟进依据", "Reveals a problem without evidence to follow up"),
            (
                "回答、案例或分歧能支持调查与写作判断",
                "Answers, cases, or disagreements support investigation and editorial judgment",
            ),
            (
                "形成可验证解法或清楚的待证问题，可直接组织后续验证",
                "Verifiable solutions or clear open questions support concrete follow-up validation",
            ),
        ),
        (
            "看真实需求、争论和待解问题，热闹不自动等于值得写",
            "Assess actual needs, disagreements, and open questions; activity alone is not editorial value",
        ),
        (
            "评论不代表总体用户或独立信源，社区共识不等于事实核验",
            "Comments are not a representative population or necessarily independent sources; consensus is not fact verification",
        ),
    ),
    "项目": ContentTypeRubric(
        ("项目", "Project / open source"),
        (
            (
                "只有仓库链接或宣传，目标和实现不明",
                "Repository link or promotion only, with unclear goal and implementation",
            ),
            (
                "目标与功能清楚，但缺运行材料或实现依据",
                "Clear goal and features, but missing runnable material or implementation evidence",
            ),
            (
                "实现、文档、运行示例与已知限制可核对",
                "Checkable implementation, documentation, runnable examples, and known limits",
            ),
            (
                "运行验证、测试和维护信息完整，说明许可、安全与部署边界",
                "Complete runtime validation, tests, and maintenance information with license, security, and deployment boundaries",
            ),
        ),
        (
            "看实现细节、运行证据与用途差异，星标或代码量不算质量证明",
            "Assess implementation, runtime evidence, and use-case differences; stars or code volume do not prove quality",
        ),
        (
            ("无法判断用途或运行方法", "Cannot determine purpose or how to run it"),
            (
                "知道用途，但缺依赖、许可或运行条件",
                "Understands the purpose but lacks dependencies, license, or runtime conditions",
            ),
            ("能判断适用性并按文档尝试运行", "Can assess suitability and attempt running it from documentation"),
            (
                "运行、集成、许可和维护条件完整，可评估采用与退出成本",
                "Runtime, integration, license, and maintenance conditions support adoption and exit-cost assessment",
            ),
        ),
        (
            "看可演示的能力、实现思路与读者任务，区分玩具演示和可采用产品",
            "Assess demonstrable capability, implementation ideas, and reader tasks; distinguish a toy demo from an adoptable product",
        ),
        (
            "有仓库不等于已运行或可商用，未提供许可证不推定授权",
            "A repository does not prove operability or commercial permission; missing license is not implied authorization",
        ),
    ),
    "通用": ContentTypeRubric(
        ("通用（类型缺失或未识别）", "General (missing or unrecognized type)"),
        (
            ("内容不可读、空泛或无依据", "Unreadable, empty, or unsupported content"),
            ("主张清楚但支撑有限", "Clear claim with limited support"),
            ("具体事实、案例或推理支撑主张，边界清楚", "Specific facts, cases, or reasoning support bounded claims"),
            (
                "完整一手材料或系统验证支撑重要新信息",
                "Complete primary material or systematic validation supports significant new information",
            ),
        ),
        (
            "按有效事实、解释或方法占比判断；不能因类型缺失降低分数或强套教程要求",
            "Assess useful facts, explanations, or methods; missing type must not lower scores or force tutorial requirements",
        ),
        (
            ("没有可用信息或判断依据", "No usable information or decision basis"),
            ("可作背景参考，但用途不清楚", "Background reference with unclear use"),
            ("可支持具体理解、选择、跟进或实践", "Supports concrete understanding, choices, follow-ups, or practice"),
            (
                "使用条件、依据和限制充分，可支持可核对的后续行动或判断",
                "Sufficient conditions, evidence, and limits support checkable action or judgment",
            ),
        ),
        (
            "看具体读者、新信息和可展开角度，不凭分类缺失或主题热度打分",
            "Assess specific readers, new information, and extensible angles, not missing labels or topic popularity",
        ),
        (
            "不猜造细分类型，不因类型未知给固定低分；不足的依据要在推荐理由中说明",
            "Do not invent a subtype or assign fixed low scores for unknown types; state evidence limits in the recommendation",
        ),
    ),
}


def resolve_rubric_type(content_type: str | None) -> str:
    normalized = normalize_content_type(content_type)
    return normalized if normalized in CONTENT_TYPE_RUBRICS else "通用"


def content_type_rubric_section(content_type: str | None, lang: str = "zh") -> str:
    """只取一个类型；四档同源、语言逐字段对齐，适用于Pro和Lite。"""
    rubric = CONTENT_TYPE_RUBRICS[resolve_rubric_type(content_type)]
    index = 1 if lang == "en" else 0

    def bands(values: Bands) -> str:
        return "; ".join(f"{lo}-{hi}={value[index]}" for (lo, hi), value in zip(ANCHOR_BANDS, values, strict=True))

    if lang == "en":
        lines = [
            f"Content-type rubric [{RUBRIC_VERSION}]: {rubric.label[index]}",
            "Use this rubric for quality_score, info_density, actionability, and creator_score. It takes precedence over generic descriptions for these fields; keep existing weights, thresholds, and risk rules. Interpolate between bands; do not give a fixed bonus for a type.",
            f"quality_score: {bands(rubric.quality)}",
            f"info_density: {rubric.density[index]}. Use the same bands for the proportion of supported, useful information: almost none / some / substantial / consistently dense; do not copy quality_score.",
            f"actionability: {bands(rubric.actionability)}",
            f"creator_score: {rubric.creator[index]}",
            f"Evidence caveat: {rubric.caution[index]}",
            "Score only supplied evidence. A missing body, date, engagement count, or test result is unknown, not proof of zero heat, freshness, or quality. Do not invent facts, experiments, consensus, or verification. State material evidence limits in recommendation (or Lite reason). High scores require positive support, not absence of contrary evidence.",
            "Source authority depends on traceability and relevance, not prestige alone. Distinguish primary claims from independently verified results. Type labels are context, not evidence; when the text contradicts the label, do not invent missing support.",
            "Lite prescreen uses the same type-specific evidence standard for score; if evidence is insufficient or the label conflicts with the text, lower confidence and escalate rather than confidently reject. Local fallback estimates are not verified type-specific judgments.",
        ]
    else:
        lines = [
            f"内容类型标尺 [{RUBRIC_VERSION}]：{rubric.label[index]}",
            "quality_score、info_density、actionability、creator_score按本标尺判断，优先于这些字段的通用描述；保持既有权重、门槛和风险规则。档间按程度插值，不因类型给固定加分。",
            f"quality_score：{bands(rubric.quality)}",
            f"info_density：{rubric.density[index]}。按同一四档判断有效且有依据的信息占比：几乎没有/部分/充实/持续高密度，不直接照抄quality_score。",
            f"actionability：{bands(rubric.actionability)}",
            f"creator_score：{rubric.creator[index]}",
            f"证据反例：{rubric.caution[index]}",
            "只评输入中可见的证据。正文、日期、互动量或实测结果缺失表示未知，不证明热度、新鲜度或质量为零；不得补造事实、实验、共识或核验。影响结论的证据不足须在recommendation（Lite用reason）中说明。高分需要正面依据，不能因为未见反证就给高分。",
            "来源权威度看可回查性与具体领域依据，不凭名气判定；区分一手声明与独立验证。类型标签只作上下文，正文与标签冲突时不能编造缺失证据。",
            "Lite预筛的score同样按该类型证据判断；材料不足或类型与正文冲突时降低confidence并升级，不得自信淘汰。本地降级估分不代表经过类型化验证。",
        ]
    return "\n".join(lines)
