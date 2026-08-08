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
    # 日报/周报/月报的 user prompt 必须保留中文摘要式推荐理由这一核心契约。
    prompts = [
        ACTIVE_DAILY_REPORT_PROMPT,
        DIGEST_PROMPT,
    ]

    for prompt in prompts:
        assert "中文摘要式推荐理由" in prompt
        assert "先概括这条内容讲了什么" in prompt

    # 英文禁令现由日报 SYSTEM_PROMPT 承载（与 ANALYSIS 的分层一致）。
    assert "不要输出英文" in DAILY_SYSTEM_PROMPT
