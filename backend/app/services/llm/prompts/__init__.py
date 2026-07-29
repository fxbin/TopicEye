"""
Prompt template registry.

Each submodule exposes module-level constants for the prompts used by
a specific service layer.  Import the ones you need:

    from app.services.llm.prompts.analysis import SYSTEM_PROMPT, ANALYSIS_PROMPT
    from app.services.llm.prompts.enrichment import SYSTEM_PROMPT, ENRICHMENT_PROMPT
    from app.services.llm.prompts.creation import PLATFORM_PROMPTS

注意：日报/周报/月报 prompt 内联在各自 service（daily_report.py 等），
不在此目录注册。
"""
