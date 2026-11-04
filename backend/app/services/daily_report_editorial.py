"""Deterministic editorial checks, not a verifier of arbitrary factual claims."""

from __future__ import annotations

import re
from typing import Any

_SLOTS = re.compile(r"(?<![A-Za-z0-9])[XYZAB](?![A-Za-z0-9])")
_TEMPLATE = re.compile(r"真正问题不是|(?:这一步|这步).{0,12}天花板|别再用|拆开看")
_REFERENCES = re.compile(r"(?<![A-Za-z0-9_/])[#＃]\s*(\d+)")


def editorial_issues(value: Any, source_title: str = "") -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return ["missing_text"]
    issues = []
    if len(set(_SLOTS.findall(value))) >= 2 and _TEMPLATE.search(value):
        issues.append("unfilled_title_template")
    # Genuine external issue numbers present in the source title remain valid.
    known = set(_REFERENCES.findall(source_title))
    if set(_REFERENCES.findall(value)) - known:
        issues.append("unresolved_material_reference")
    return issues


def conservative_reason(item: dict) -> str:
    title = item["title"]
    for field in ("summary", "recommendation"):
        value = item.get(field)
        if not editorial_issues(value, title):
            return f"素材摘要：{value.strip()}"
    return "请阅读原文，核对具体变化和适用范围后再决定是否跟进。"


def review_daily_pick(pick: dict, item: dict) -> tuple[dict, list[str]]:
    """Keep identity in the caller; uncertain editorial text becomes a brief."""
    result = dict(pick)
    title = item["title"]
    issues = []
    supplied_source = pick.get("source_title")
    if (
        supplied_source is not None
        and supplied_source != ""
        and (not isinstance(supplied_source, str) or supplied_source.strip() != title.strip())
    ):
        issues.append("source_title_mismatch")
    if pick.get("editorial_title"):
        issues.extend(editorial_issues(pick["editorial_title"], title))
    issues.extend(editorial_issues(pick.get("reason"), title))
    if issues:
        # Do not retain lifecycle/angles derived from a rejected editorial claim.
        return {
            "source_idx": pick.get("source_idx"),
            "source_title": title,
            "editorial_title": title,
            "reason": conservative_reason(item),
            "category": item.get("category", "未分类"),
            "tier": "brief",
            "platforms": [],
        }, sorted(set(issues))
    for field in ("source_title_zh", "pitfall", "time_window"):
        if result.get(field) is None or result.get(field) == "":
            result.pop(field, None)
            continue
        if editorial_issues(result[field], title):
            result.pop(field)
            issues.append(f"invalid_{field}")
    if "angles" in result:
        angles = result["angles"]
        result["angles"] = [a for a in angles if not editorial_issues(a, title)] if isinstance(angles, list) else []
        if result["angles"] != angles:
            issues.append("invalid_angles")
    if result.get("tier", "feature") not in ("feature", "brief"):
        result["tier"] = "brief"
        issues.append("invalid_tier")
    if not isinstance(result.get("category", ""), str):
        result["category"] = item.get("category", "未分类")
        issues.append("invalid_category")
    platforms = result.get("platforms")
    result["platforms"] = (
        list(dict.fromkeys(p for p in platforms if isinstance(p, str) and p.strip()))
        if isinstance(platforms, list)
        else []
    )
    return result, issues


def review_daily_sections(result: dict, fallback: dict, source_titles: str) -> tuple[dict, list[str]]:
    """Validate public text without pretending syntactic checks prove facts."""
    cleaned = dict(result)
    issues = []
    for field in ("overview", "takeaway"):
        if editorial_issues(result.get(field), source_titles):
            cleaned[field] = fallback[field]
            issues.append(f"invalid_{field}")
    trends = result.get("trends")
    cleaned["trends"] = []
    if isinstance(trends, list):
        for trend in trends:
            if not isinstance(trend, dict) or editorial_issues(trend.get("title"), source_titles):
                issues.append("invalid_trend")
                continue
            description = trend.get("desc")
            if description is not None and (
                not isinstance(description, str) or (description and editorial_issues(description, source_titles))
            ):
                issues.append("invalid_trend")
                continue
            cleaned_trend = {"title": trend["title"], "desc": description or ""}
            momentum = trend.get("momentum", "stable")
            if isinstance(momentum, str) and momentum in {"up", "down", "stable"}:
                cleaned_trend["momentum"] = momentum
            else:
                cleaned_trend["momentum"] = "stable"
                issues.append("invalid_trend_momentum")
            color = trend.get("color")
            if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                cleaned_trend["color"] = color
            elif color is not None:
                issues.append("invalid_trend_color")
            cleaned["trends"].append(cleaned_trend)
    tips = result.get("platform_tips")
    cleaned["platform_tips"] = {}
    if isinstance(tips, dict):
        for platform, texts in tips.items():
            if editorial_issues(platform) or not isinstance(texts, list):
                issues.append("invalid_platform_tips")
                continue
            valid = [t for t in texts if not editorial_issues(t, source_titles)]
            if len(valid) != len(texts):
                issues.append("invalid_platform_tips")
            if valid:
                cleaned["platform_tips"][platform] = valid
    keywords = result.get("keywords")
    cleaned["keywords"] = (
        [k for k in keywords if not editorial_issues(k, source_titles)] if isinstance(keywords, list) else []
    )
    return cleaned, sorted(set(issues))
