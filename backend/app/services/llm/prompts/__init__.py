"""
Prompt template registry.

Each submodule exposes module-level constants for the prompts used by
a specific service layer.  Import the ones you need:

    from app.services.llm.prompts.analysis import SYSTEM_PROMPT, ANALYSIS_PROMPT
    from app.services.llm.prompts.enrichment import SYSTEM_PROMPT, ENRICHMENT_PROMPT
    from app.services.llm.prompts.creation import PLATFORM_PROMPTS
    from app.services.llm.prompts.daily_report import SYSTEM_PROMPT, REPORT_PROMPT
    from app.services.llm.prompts.angle_recommend import SYSTEM_PROMPT, USER_TEMPLATE

所有 service 的 prompt 均已抽取到此目录，无内联 prompt。
"""
