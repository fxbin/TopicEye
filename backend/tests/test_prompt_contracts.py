from app.services.daily_report import REPORT_PROMPT as ACTIVE_DAILY_REPORT_PROMPT, SYSTEM_PROMPT as DAILY_SYSTEM_PROMPT
from app.services.llm.prompts.analysis import ANALYSIS_PROMPT, ANALYSIS_PROMPT_EN, SYSTEM_PROMPT_EN
from app.services.llm.prompts.digest import DIGEST_PROMPT


def test_analysis_recommendation_is_required_as_chinese_summary():
    assert "中文摘要式推荐理由" in ANALYSIS_PROMPT
    assert "不要英文" in ANALYSIS_PROMPT
    assert "all output text must be Chinese" in SYSTEM_PROMPT_EN
    assert "中文摘要式推荐理由" in ANALYSIS_PROMPT_EN
    assert "不要输出英文" in ANALYSIS_PROMPT_EN


def test_report_top_pick_reasons_are_required_as_chinese_summaries():
    assert "中文摘要式推荐理由" in DIGEST_PROMPT
    assert "先概括这条内容讲了什么" in DIGEST_PROMPT

    # #231的日报改为具体编辑合同，规则在system，reason字段在user；
    # 保留事实→读者价值的要求，不再要求已退役的逐字模板措辞。
    assert '"reason"' in ACTIVE_DAILY_REPORT_PROMPT
    assert "推荐理由先交代这条素材的新信息" in DAILY_SYSTEM_PROMPT
    assert "再说明对哪类读者有用" in DAILY_SYSTEM_PROMPT
    assert "除原文标题、专有名词与术语外用中文" in DAILY_SYSTEM_PROMPT
