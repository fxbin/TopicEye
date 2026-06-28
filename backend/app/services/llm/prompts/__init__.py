"""
Prompt template registry.

Each submodule exposes module-level constants for the prompts used by
a specific service layer.  Import the ones you need:

    from app.services.llm.prompts.analysis import SYSTEM_PROMPT, ANALYSIS_PROMPT
    from app.services.llm.prompts.enrichment import SYSTEM_PROMPT, ENRICHMENT_PROMPT
    from app.services.llm.prompts.creation import PLATFORM_PROMPTS
    from app.services.llm.prompts.report import REPORT_PROMPT

注意：去重 prompt 内联在 semantic_dedup.py（不在此目录），勿在此添加。
"""
