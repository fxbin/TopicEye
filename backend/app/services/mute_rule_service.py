"""用户自定义降噪规则（#171）的业务编排与匹配语义。

三类规则（对当前用户可见的 contents 列表与 today-picks 生效，只排除可见项，
不物理删除或改写内容数据，与 ignored_items 排除叠加）：

- ``keyword``：value 对 title/summary 大小写不敏感**包含**（SQL 侧 ILIKE %v%，
  Python 侧 lower 后子串判断，两端口径一致——写入时已做 LIKE 通配符转义）；
- ``source``  ：value 为信源 ID 的字符串形式，与 ``content_items.source_id``
  精确等值；
- ``domain``  ：value 已归一（小写、去 ``www.`` 前缀、去协议/路径/端口），
  与内容 url 的 host 等值比较。

本模块只做校验、归一与纯匹配函数；IO 经 ``MuteRuleRepository``，
重查询过滤下沉在 repository 层（见 ``_query_helpers.apply_mute_rule_exclusions``）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, ValidationError
from app.models.mute_rule import MuteRule
from app.repositories.mute_rule_repo import MuteRuleRepository

MUTE_RULE_TYPES = ("keyword", "source", "domain")
"""rule_type 的合法取值（与表级 CHECK 约束 ck_mute_rules_rule_type 一致）。"""

MAX_RULES_PER_TYPE = 50
"""每类规则每用户上限（service 层校验，防误操作刷库）。"""

KEYWORD_MAX_LENGTH = 100
VALUE_MAX_LENGTH = 255


# ── 值归一与校验 ──────────────────────────────────────────────────────


def _split_host(raw: str) -> str:
    """从任意 url/host 字符串提取小写 host：去协议、路径、查询、端口。"""
    text = raw.strip().lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0]
    text = text.split("?", 1)[0]
    text = text.split("#", 1)[0]
    text = text.split(":", 1)[0]
    return text


def strip_www(host: str) -> str:
    """去掉 host 的 ``www.`` 前缀（仅一个，避免误伤 ``wwwexample.com``）。"""
    return host[4:] if host.startswith("www.") else host


def normalize_rule_value(rule_type: str, raw: str) -> str:
    """按规则类型归一 value；非法输入抛 ``ValidationError``。

    - keyword：去首尾空白，长度 1-100；
    - source ：必须是数字（信源 ID），归一去前导零；
    - domain ：提取 host 并去 ``www.`` 前缀后小写存储（写入侧归一，
      SQL 匹配侧同样归一 url host，两侧对齐）。
    """
    if rule_type not in MUTE_RULE_TYPES:
        raise ValidationError(f"rule_type 必须是 {'/'.join(MUTE_RULE_TYPES)} 之一，收到 {rule_type!r}")
    if raw is None or not str(raw).strip():
        raise ValidationError("value 不能为空")

    value = str(raw).strip()
    if rule_type == "keyword":
        if len(value) < 1 or len(value) > KEYWORD_MAX_LENGTH:
            raise ValidationError(f"关键词长度需在 1-{KEYWORD_MAX_LENGTH} 之间")
        return value

    if rule_type == "source":
        if not value.isdigit():
            raise ValidationError("source 规则的 value 必须是信源 ID（数字）")
        return str(int(value))

    # domain
    host = strip_www(_split_host(value))
    if not host or len(host) > VALUE_MAX_LENGTH or any(ch.isspace() for ch in host):
        raise ValidationError("domain 规则的 value 必须是合法域名（如 example.com）")
    return host


def url_host_normalized(url: str | None) -> str:
    """匹配侧的 url host 归一（小写、去路径/查询/端口、去 ``www.``）。

    与 SQL 侧 ``url_host_expression`` 同前提：url 必须带协议（含 ``://``）；
    无协议的值不参与匹配（返回空串，永不命中），两侧不留隐性分叉。
    """
    if not url or "://" not in str(url):
        return ""
    try:
        hostname = urlparse(str(url)).hostname
    except ValueError:
        hostname = None
    return strip_www((hostname or "").lower())


# ── 匹配语义（纯函数，无 IO） ─────────────────────────────────────────


@dataclass(frozen=True)
class MuteExclusions:
    """三类规则的匹配集；为空表示该用户没有任何静音规则。"""

    keywords: tuple[str, ...] = ()
    source_ids: frozenset[int] = field(default_factory=frozenset)
    domains: frozenset[str] = field(default_factory=frozenset)

    def __bool__(self) -> bool:
        return bool(self.keywords or self.source_ids or self.domains)


def rules_to_exclusions(rules: Iterable[Mapping[str, Any] | MuteRule]) -> MuteExclusions:
    """把规则行折算成匹配集（兼容 ORM 对象与 dict）。"""
    keywords: list[str] = []
    source_ids: set[int] = set()
    domains: set[str] = set()
    for rule in rules:
        rule_type = rule["rule_type"] if isinstance(rule, Mapping) else rule.rule_type
        value = rule["value"] if isinstance(rule, Mapping) else rule.value
        if rule_type == "keyword":
            keywords.append(value)
        elif rule_type == "source":
            if str(value).isdigit():
                source_ids.add(int(value))
        elif rule_type == "domain":
            domains.add(value)
    return MuteExclusions(
        keywords=tuple(keywords),
        source_ids=frozenset(source_ids),
        domains=frozenset(domains),
    )


def row_is_muted(row: Mapping[str, Any], exclusions: MuteExclusions) -> bool:
    """today-picks row dict 是否命中任一静音规则。

    与 SQL 侧（ILIKE / source 等值 / host 等值）口径一致：
    keyword 大小写不敏感子串；source 精确等值；domain 为归一 host 等值。
    """
    title = str(row.get("title") or "").lower()
    summary = str(row.get("summary") or "").lower()
    for keyword in exclusions.keywords:
        needle = keyword.lower()
        if needle in title or needle in summary:
            return True
    if row.get("source_id") is not None and int(row["source_id"]) in exclusions.source_ids:
        return True
    return bool(exclusions.domains) and url_host_normalized(row.get("url")) in exclusions.domains


def filter_muted_rows(rows: Sequence[Mapping[str, Any]], exclusions: MuteExclusions) -> list[Mapping[str, Any]]:
    """批量剔除命中的 row（保持原顺序）。"""
    if not exclusions:
        return list(rows)
    return [row for row in rows if not row_is_muted(row, exclusions)]


# ── 业务编排（IO 经 repository） ──────────────────────────────────────


async def load_mute_exclusions(db: AsyncSession, user_id: int | None) -> MuteExclusions:
    """读取当前用户的静音规则并折算成匹配集（匿名/无规则返回空集）。"""
    if user_id is None:
        return MuteExclusions()
    rules = await MuteRuleRepository(db).list_for_user(user_id)
    return rules_to_exclusions(rules)


async def list_mute_rules(db: AsyncSession, user_id: int) -> Sequence[MuteRule]:
    return await MuteRuleRepository(db).list_for_user(user_id)


async def create_mute_rule(db: AsyncSession, *, user_id: int, rule_type: str, value: str) -> MuteRule:
    """校验 → 查重 → 上限 → 写入；唯一约束冲突（含并发竞态）返回 409 语义。"""
    normalized = normalize_rule_value(rule_type, value)
    repo = MuteRuleRepository(db)
    if await repo.get_by_value(user_id, rule_type, normalized) is not None:
        raise AlreadyExistsError("静音规则", field=f"{rule_type}:{normalized}")
    if await repo.count_for_user(user_id, rule_type) >= MAX_RULES_PER_TYPE:
        raise ValidationError(f"每类静音规则最多 {MAX_RULES_PER_TYPE} 条，可先删除部分规则")
    try:
        return await repo.create_rule(user_id, rule_type, normalized)
    except IntegrityError as exc:
        # 并发窗口内撞唯一约束：归一后的值已存在
        await db.rollback()
        raise AlreadyExistsError("静音规则", field=f"{rule_type}:{normalized}") from exc


async def delete_mute_rule(db: AsyncSession, *, user_id: int, rule_id: int) -> bool:
    """删除当前用户的一条规则；不存在/他人规则返回 False。"""
    return await MuteRuleRepository(db).delete_for_user(user_id, rule_id)
