"""
LLM 规则过滤层测试（参照 content-signal-radar lowSignalPenalty 设计）。

覆盖：
- 硬低信号（GM/happy birthday/milestone/pure emoji）→ skip
- 软低信号（自吹自擂无技术细节）→ skip
- 短内容（< 30 字符）→ skip
- 正常内容 → pass
- 空文本 → skip (no_text)
- cumulative counter get_skip_count()
"""

from __future__ import annotations

import pytest

from app.services.llm_pre_filter import (
    _is_hard_low_signal,
    _is_soft_low_signal,
    _is_too_short,
    apply_pre_filter,
    get_skip_count,
    should_skip_analysis,
)


def make_item(title="", summary="", raw_content=""):
    """Mock ContentItem with just the fields the pre-filter checks."""

    class _Item:
        pass

    item = _Item()
    item.title = title
    item.summary = summary
    item.raw_content = raw_content
    item.skip_analysis = False
    item.skip_reason = None
    item.id = 1
    return item


# ── _is_hard_low_signal ────────────────────────────────────────────


class TestHardLowSignal:
    @pytest.mark.parametrize(
        "text",
        [
            "GM everyone! Have a great day 🚀",
            "Happy birthday to my dear friend",
            "Merry Christmas from our team",
            "Happy Friday!",
            "Good morning!",
            "Just hit 1000 followers 🎉",
            "10k followers milestone",
            "🚀🚀🚀",
            "🙏🙏",
        ],
    )
    def test_should_skip(self, text):
        assert _is_hard_low_signal(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "AI agents reshape software procurement",
            "How to use Python for async tasks",
            "Analysis: 7 new LLM benchmarks",
        ],
    )
    def test_should_not_skip(self, text):
        assert _is_hard_low_signal(text) is False


# ── _is_soft_low_signal ────────────────────────────────────────────


class TestSoftLowSignal:
    def test_self_promo_no_tech_detail(self):
        assert _is_soft_low_signal("My new SaaS is the best!") is True

    def test_self_promo_with_tech_detail(self):
        # self-promo + tech keyword → 不算软低信号
        assert _is_soft_low_signal("My new API handles 10k QPS with sub-100ms latency") is False

    def test_normal_content(self):
        assert _is_soft_low_signal("OpenAI releases GPT-5 with reasoning capabilities") is False


# ── _is_too_short ──────────────────────────────────────────────────


class TestTooShort:
    def test_short(self):
        assert _is_too_short("hi") is True

    def test_30_chars(self):
        assert _is_too_short("a" * 30) is False  # exactly 30 → not too short

    def test_29_chars(self):
        assert _is_too_short("a" * 29) is True

    def test_empty(self):
        assert _is_too_short("") is True


# ── should_skip_analysis (顶层) ────────────────────────────────────


class TestShouldSkip:
    def test_no_text(self):
        item = make_item()
        skip, reason = should_skip_analysis(item)
        assert skip is True
        assert reason == "no_text"

    def test_hard_low_signal(self):
        item = make_item(title="GM everyone! Happy Friday!")
        skip, reason = should_skip_analysis(item)
        assert skip is True
        assert reason == "hard_low_signal"

    def test_self_promo(self):
        # 用足够长的纯自吹（无 tech keyword 命中）
        item = make_item(
            title="My new project just launched, would love your support!",
            summary="Check it out and let me know what you think friends",
        )
        skip, reason = should_skip_analysis(item)
        assert skip is True
        assert reason == "self_promo"

    def test_short_text(self):
        item = make_item(title="hi", summary="", raw_content="")
        skip, reason = should_skip_analysis(item)
        assert skip is True
        assert reason == "short_text"

    def test_normal_content_passes(self):
        item = make_item(
            title="How AI agents reshape software procurement",
            summary="Analysis: 7 key findings from enterprise AI adoption",
            raw_content="A detailed 500-word analysis of how AI agents are changing...",
        )
        skip, reason = should_skip_analysis(item)
        assert skip is False
        assert reason is None


# ── apply_pre_filter (mutating) ─────────────────────────────────────


class TestApplyPreFilter:
    def test_skip_sets_flags(self):
        item = make_item(title="GM!")
        apply_pre_filter(item)
        assert item.skip_analysis is True
        assert item.skip_reason == "hard_low_signal"

    def test_pass_leaves_flags(self):
        item = make_item(
            title="How AI agents reshape software procurement",
            summary="Detailed analysis with benchmarks and case studies",
        )
        result = apply_pre_filter(item)
        assert result is False
        assert item.skip_analysis is False
        assert item.skip_reason is None


# ── cumulative counter ─────────────────────────────────────────────


class TestSkipCount:
    def test_initial_zero(self):
        # Note: counter is module-global, may be > 0 from earlier tests
        initial = get_skip_count()
        assert initial >= 0

    def test_counter_increments(self):
        before = get_skip_count()
        apply_pre_filter(make_item(title="GM!"))
        apply_pre_filter(make_item(title="Happy Friday!"))
        after = get_skip_count()
        assert after == before + 2


# ── 回归测试:apply_pre_filter 不 skip 时必须显式写 skip_analysis=False ──
# 背景:之前 apply_pre_filter 只在 skip=True 时写属性,skip=False 时不动。
# 新建 ContentItem 的 instance attribute 默认是 None,SQLAlchemy flush 时
# 把 None 发到 NOT NULL 列 → PG 抛 NotNullViolationError,source 同步整批
# INSERT 全部回滚,sync_error 被记为 "null value in column skip_analysis"。
# 修复后:不 skip 时显式写 False,INSERT 携带明确值,绕开 instance 未刷新歧义。


def test_apply_pre_filter_writes_false_when_not_skipped():
    """不 skip 时,apply_pre_filter 必须显式写 skip_analysis=False,不能留 None。"""
    from app.models.content import ContentItem, ContentStatus

    item = ContentItem(
        title="正常内容",
        url="https://example.com/no-skip-test",
        source_id=1,
        source_name="test",
        source_type="RSS",
        status=ContentStatus.PENDING,
        summary="这是一段正常长度的内容，应该不会触发 skip 规则。" * 5,
    )
    # 关键:新建对象 skip_analysis 应该是 None(instance 未填)
    assert item.skip_analysis is None, "新建对象 skip_analysis 应为 None,不是 False"

    apply_pre_filter(item)

    # 验证属性是 False 不是 None(否则 INSERT 会发 NULL 到 NOT NULL 列)
    assert item.skip_analysis is False, f"apply_pre_filter 后 skip_analysis 必须是 False,不能是 {item.skip_analysis!r}"
    assert item.skip_reason is None
