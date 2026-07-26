"""PromptRegistry — read-only catalog of LLM prompt templates.

Stores metadata about each prompt template used in the system so that
administrators can view which prompts exist, where they're defined,
and how often they're called (via the ``scene`` field on ``LlmCallLog``).

This is a **read-only registry**: the actual prompt text still lives in
``app.services.llm.prompts.*`` Python modules. The DB row is synced at
startup and serves as a catalog entry — it is not the source of truth
for prompt content at runtime.

Design:
1. One row per named prompt template (e.g. ``analysis``, ``classification``).
2. ``scene`` maps to ``LlmCallLog.scene`` for join queries.
3. ``source_file`` records which Python module defines the prompt.
4. ``content_preview`` stores the first 500 chars for quick admin browsing.
5. ``full_content`` stores the complete prompt text (synced at startup).
6. No mutation API — prompts are changed via code changes + deploy, not via DB.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PromptRegistry(Base):
    """Read-only catalog of LLM prompt templates."""

    __tablename__ = "prompt_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    # Maps to LlmCallLog.scene for usage stats join
    scene: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Human-readable description
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Which Python module defines this prompt
    source_file: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # First 500 chars for quick browsing
    content_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Full prompt text (synced at startup, read-only at runtime)
    full_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Version hash (md5 of full_content) to detect changes
    version_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<PromptRegistry {self.name} scene={self.scene}>"
