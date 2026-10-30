"""用户降噪规则（#171）service 层：值归一 / 匹配语义 / 上限 / 唯一冲突。

匹配语义是 contents 列表（SQL 侧）与 today-picks（Python 侧）两条链路的
共同口径，这里用纯函数单测钉住：

- keyword 大小写不敏感包含（title 或 summary 任一命中）；
- source 信源 ID 精确等值；
- domain 为 url host 归一（去协议/路径/端口/www.）后等值。

service 的 IO 编排（查重、每类上限 50、唯一约束冲突→409）走 in-memory
SQLite（``db`` fixture，纯业务逻辑单测约定）。
"""

from __future__ import annotations

import pytest

from app.core.exceptions import AlreadyExistsError, ValidationError
from app.models.mute_rule import MuteRule
from app.services import mute_rule_service
from app.services.mute_rule_service import (
    MAX_RULES_PER_TYPE,
    MuteExclusions,
    filter_muted_rows,
    normalize_rule_value,
    row_is_muted,
    rules_to_exclusions,
    url_host_normalized,
)

# ── normalize_rule_value ──────────────────────────────────────────────


class TestNormalizeRuleValue:
    def test_keyword_strips_whitespace(self):
        assert normalize_rule_value("keyword", "  静音词  ") == "静音词"

    def test_keyword_length_bounds(self):
        with pytest.raises(ValidationError):
            normalize_rule_value("keyword", "   ")
        with pytest.raises(ValidationError):
            normalize_rule_value("keyword", "a" * 101)
        assert normalize_rule_value("keyword", "a" * 100) == "a" * 100

    def test_source_must_be_digits_and_normalized(self):
        assert normalize_rule_value("source", "007") == "7"
        with pytest.raises(ValidationError):
            normalize_rule_value("source", "example.com")

    def test_domain_normalized_to_bare_host(self):
        assert normalize_rule_value("domain", "https://WWW.Example.com/path?q=1") == "example.com"
        assert normalize_rule_value("domain", "www.example.com") == "example.com"
        assert normalize_rule_value("domain", "example.com:8080/x") == "example.com"

    def test_domain_rejects_empty_and_space(self):
        with pytest.raises(ValidationError):
            normalize_rule_value("domain", "https:///")
        with pytest.raises(ValidationError):
            normalize_rule_value("domain", "bad domain.com")

    def test_invalid_rule_type_rejected(self):
        with pytest.raises(ValidationError):
            normalize_rule_value("regex", "whatever")

    def test_empty_value_rejected_for_every_type(self):
        for rule_type in ("keyword", "source", "domain"):
            with pytest.raises(ValidationError):
                normalize_rule_value(rule_type, "  ")


# ── url_host_normalized（匹配侧与 SQL 侧 url_host_expression 同前提）────


class TestUrlHostNormalized:
    def test_full_url_with_www_and_port(self):
        assert url_host_normalized("https://www.Noisy.example.com:443/a?b=1") == "noisy.example.com"

    def test_scheme_less_url_does_not_participate(self):
        # 与 SQL 侧同前提：url 必须带协议；无协议求值为空、永不命中
        assert url_host_normalized("example.com/path") == ""
        assert url_host_normalized("www.example.com") == ""

    def test_none_or_empty(self):
        assert url_host_normalized(None) == ""
        assert url_host_normalized("") == ""


# ── row_is_muted / filter_muted_rows ─────────────────────────────────


def _row(**overrides):
    base = {
        "id": 1,
        "title": "AI 大模型发布",
        "summary": "某公司发布新模型",
        "url": "https://example.com/a",
        "source_id": 7,
    }
    base.update(overrides)
    return base


class TestRowIsMuted:
    def test_keyword_case_insensitive_on_title_or_summary(self):
        exclusions = rules_to_exclusions([{"rule_type": "keyword", "value": "GPT"}])
        assert row_is_muted(_row(title="New gpt-5 released"), exclusions)
        assert row_is_muted(_row(summary="summaries mention Gpt here"), exclusions)
        assert not row_is_muted(_row(title="其它新闻", summary="无关"), exclusions)

    def test_keyword_literal_percent_is_not_wildcard(self):
        exclusions = rules_to_exclusions([{"rule_type": "keyword", "value": "100%"}])
        assert row_is_muted(_row(title="增长 100% 的季度"), exclusions)
        assert not row_is_muted(_row(title="增长 100万 的季度"), exclusions)

    def test_source_exact_match(self):
        exclusions = rules_to_exclusions([{"rule_type": "source", "value": "7"}])
        assert row_is_muted(_row(source_id=7), exclusions)
        assert not row_is_muted(_row(source_id=8), exclusions)
        assert not row_is_muted(_row(source_id=None), exclusions)

    def test_domain_host_equality_after_normalization(self):
        exclusions = rules_to_exclusions([{"rule_type": "domain", "value": "noisy.example.com"}])
        assert row_is_muted(_row(url="https://www.noisy.example.com/post/1"), exclusions)
        assert row_is_muted(_row(url="http://noisy.example.com:8080/x"), exclusions)
        assert not row_is_muted(_row(url="https://example.com/noisy.example.com"), exclusions)

    def test_empty_exclusions_matches_nothing(self):
        assert not row_is_muted(_row(), MuteExclusions())
        assert bool(MuteExclusions()) is False

    def test_filter_muted_rows_preserves_order(self):
        exclusions = rules_to_exclusions([{"rule_type": "keyword", "value": "噪音"}])
        rows = [_row(id=1, title="keep A"), _row(id=2, title="噪音内容"), _row(id=3, title="keep B")]
        assert [row["id"] for row in filter_muted_rows(rows, exclusions)] == [1, 3]
        # 空规则集原样返回
        assert [row["id"] for row in filter_muted_rows(rows, MuteExclusions())] == [1, 2, 3]


# ── service 编排（in-memory SQLite） ─────────────────────────────────


async def _make_user(db, email: str = "u@example.com") -> int:
    from app.services.auth_service import create_user

    user = await create_user(db, email=email, password="Password123")
    return user.id


class TestServiceCrud:
    pytestmark = pytest.mark.asyncio

    async def test_create_normalizes_value_before_storing(self, db):
        user_id = await _make_user(db)
        rule = await mute_rule_service.create_mute_rule(
            db, user_id=user_id, rule_type="domain", value="www.Noisy.com/x"
        )
        assert rule.value == "noisy.com"

    async def test_duplicate_returns_conflict(self, db):
        user_id = await _make_user(db)
        await mute_rule_service.create_mute_rule(db, user_id=user_id, rule_type="keyword", value="dup")
        # 完全相同的值重复创建 → 409
        with pytest.raises(AlreadyExistsError):
            await mute_rule_service.create_mute_rule(db, user_id=user_id, rule_type="keyword", value="dup")
        # domain 归一后相同（大小写/路径差异）也算重复
        await mute_rule_service.create_mute_rule(db, user_id=user_id, rule_type="domain", value="noisy.com")
        with pytest.raises(AlreadyExistsError):
            await mute_rule_service.create_mute_rule(
                db, user_id=user_id, rule_type="domain", value="https://Noisy.com/a"
            )

    async def test_per_type_limit_enforced(self, db):
        user_id = await _make_user(db)
        for i in range(MAX_RULES_PER_TYPE):
            db.add(MuteRule(user_id=user_id, rule_type="keyword", value=f"kw-{i}"))
        await db.flush()
        with pytest.raises(ValidationError, match="最多"):
            await mute_rule_service.create_mute_rule(db, user_id=user_id, rule_type="keyword", value="overflow")
        # 其它类型不受影响
        rule = await mute_rule_service.create_mute_rule(db, user_id=user_id, rule_type="domain", value="ok.example.com")
        assert rule.value == "ok.example.com"

    async def test_rules_are_user_scoped(self, db):
        alice = await _make_user(db, "alice@example.com")
        bob = await _make_user(db, "bob@example.com")
        rule = await mute_rule_service.create_mute_rule(db, user_id=alice, rule_type="keyword", value="secret")
        assert [r.value for r in await mute_rule_service.list_mute_rules(db, alice)] == ["secret"]
        assert await mute_rule_service.list_mute_rules(db, bob) == []
        # Bob 删不了 Alice 的规则
        assert await mute_rule_service.delete_mute_rule(db, user_id=bob, rule_id=rule.id) is False
        assert await mute_rule_service.delete_mute_rule(db, user_id=alice, rule_id=rule.id) is True
        assert await mute_rule_service.list_mute_rules(db, alice) == []

    async def test_load_mute_exclusions_anonymous_is_empty(self, db):
        assert not await mute_rule_service.load_mute_exclusions(db, None)

    async def test_load_mute_exclusions_buckets_by_type(self, db):
        user_id = await _make_user(db)
        for rule_type, value in (("keyword", "kw"), ("source", "12"), ("domain", "x.example.com")):
            await mute_rule_service.create_mute_rule(db, user_id=user_id, rule_type=rule_type, value=value)
        exclusions = await mute_rule_service.load_mute_exclusions(db, user_id)
        assert exclusions.keywords == ("kw",)
        assert exclusions.source_ids == frozenset({12})
        assert exclusions.domains == frozenset({"x.example.com"})
