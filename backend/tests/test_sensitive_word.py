"""敏感词扫描（service 纯函数）与 POST /content-check/sensitive（入口层）测试。

覆盖（对应任务书验收）：
1. 内置三份词库全部词条通过加载校验（零跳过——「禁止安静失败」的机器化）；
2. 各分类命中与 category/severity/suggestion 字段；
3. 同 start 保留最长词（union 按词长降序是实现前提）；
4. 重叠区间贪心：先出现者保留，结果区间两两不交且 start 升序；
5. 同区间跨类命中按严重度决胜（合成词库 monkeypatch 验证）；
6. 全角标点/空白视为分隔符，不产生跨标点命中；
7. start/end 是原文字符（codepoint）偏移，含 emoji 场景（前端按 codepoint 切分对齐）；
8. 空文本/超长文本经 Pydantic 自动 422；未认证 401；
9. 一万字扫描多次取均值 < 200ms。

测试命令：bash backend/scripts/test_full_local.sh tests/test_sensitive_word.py
（conftest 的 autouse fixture 需要一次性 PG，不能用 dummy DATABASE_URL 直跑。）
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.auth import get_current_user
from app.api.v1.content_check import router as content_check_router
from app.core.sensitive_words import (
    CATEGORIES,
    CATEGORY_ADVERTISING_EXTREME,
    CATEGORY_PLATFORM_THROTTLE,
    CATEGORY_POLITICAL_ADULT,
)
from app.services import sensitive_word_service as svc
from app.services.sensitive_word_service import load_words, scan

# ── Service：词库与纯函数 ────────────────────────────────────────────────


def test_builtin_lexicons_all_valid_and_within_size_budget():
    """内置词库零跳过：所有词条非空、不含分隔符、severity 合法；总量 ≤ 1000。"""
    total = 0
    for category in CATEGORIES:
        words = load_words(category)
        assert len(words) >= 100, f"{category} 词量异常偏少: {len(words)}"
        for entry in words:
            assert entry["word"], f"{category} 存在空词条: {entry}"
            assert not svc._SEPARATOR_RE.search(
                entry["word"]
            ), f"{category} 词条含空白/标点，会被加载校验跳过: {entry['word']!r}"
            assert entry["severity"] in ("high", "medium", "low")
        total += len(words)
    assert total <= 1000, f"词库总量超预算: {total}"


def test_scan_hits_each_category_with_metadata():
    """三类词库各命中一次，category/severity/suggestion 字段齐全。"""
    text = "这是市面上最好的选择；远离赌博；商家刷单被抓。"
    hits = scan(text)
    by_cat = {h["category"]: h for h in hits}
    assert set(by_cat) == {CATEGORY_ADVERTISING_EXTREME, CATEGORY_POLITICAL_ADULT, CATEGORY_PLATFORM_THROTTLE}
    assert by_cat[CATEGORY_ADVERTISING_EXTREME]["word"] == "最好"
    assert by_cat[CATEGORY_ADVERTISING_EXTREME]["severity"] in ("high", "medium", "low")
    assert by_cat[CATEGORY_ADVERTISING_EXTREME]["suggestion"]  # 最好 带替换建议
    assert by_cat[CATEGORY_POLITICAL_ADULT]["word"] == "赌博"
    assert by_cat[CATEGORY_PLATFORM_THROTTLE]["word"] == "刷单"


def test_same_start_keeps_longest_word():
    """同 start 多个候选时只保留最长词：全网最低价 优先于 全网最低/最低。"""
    hits = scan("本店全网最低价出售。")
    assert [h["word"] for h in hits] == ["全网最低价"]
    assert hits[0]["start"] == 2 and hits[0]["end"] == 7


def test_overlapping_intervals_resolved_greedily():
    """重叠区间：先出现者保留（销量第一 vs 起点更晚的 第一品牌），结果两两不交。"""
    hits = scan("这个是销量第一品牌的产品。")
    words = [h["word"] for h in hits]
    assert "销量第一" in words
    assert "第一品牌" not in words, "与先出现命中重叠的词条应被丢弃"
    # 结果按 start 升序且区间两两不交
    for prev, cur in zip(hits, hits[1:], strict=False):
        assert prev["start"] < cur["start"]
        assert prev["end"] <= cur["start"]


def test_no_match_across_fullwidth_punctuation_or_whitespace():
    """全角标点与空白是分隔符：不得产生跨标点命中。"""
    low = scan("全网最低，价")
    assert [h["word"] for h in low] == ["全网最低"], "逗号后的「价」不得拼进更长词条"
    assert scan("绝。对") == [], "全角句号隔开的「绝。对」不得命中「绝对」"
    assert scan("最 好用") == [], "空白隔开不得命中「最好」"
    assert scan("最、好 用") == [], "顿号与空格均视为分隔符"


def test_offsets_are_original_codepoint_coordinates():
    """start/end 是原文字符偏移（Python codepoint），emoji 不漂移。"""
    text = "😀😀这款全网最低价"
    hits = scan(text)
    assert len(hits) == 1 and hits[0]["word"] == "全网最低价"
    assert (hits[0]["start"], hits[0]["end"]) == (4, 9)
    # 任意命中都可用原文切片还原词条
    source = "加微信领福利，赌博违法，最好别碰。"
    for h in scan(source):
        assert source[h["start"] : h["end"]] == h["word"]


def test_scan_empty_and_clean_text():
    assert scan("") == []
    assert scan("一篇完全正常的科普文稿，介绍光合作用与 Coffee 的关系。") == []


def test_same_span_prefers_higher_severity_and_earlier_start(monkeypatch):
    """合成词库验证决胜规则：同区间高严重度优先；错位重叠先出现者保留。"""
    import re

    fake_entries = {
        "catA": (
            {"word": "测试词", "severity": "low", "suggestion": ""},
            {"word": "AB", "severity": "low", "suggestion": ""},
        ),
        "catB": ({"word": "测试词", "severity": "high", "suggestion": "删掉"},),
        "catC": ({"word": "BCDE", "severity": "low", "suggestion": ""},),
    }

    def fake_load(category):
        return fake_entries[category]

    def fake_patterns():
        return {
            "catA": re.compile("测试词|AB"),
            "catB": re.compile("测试词"),
            "catC": re.compile("BCDE"),
        }

    monkeypatch.setattr(svc, "_CATEGORY_FILES", {"catA": "a.json", "catB": "b.json", "catC": "c.json"})
    monkeypatch.setattr(svc, "load_words", fake_load)
    monkeypatch.setattr(svc, "_compiled_patterns", fake_patterns)

    # 同区间：catB(high) 击败 catA(low)
    hits = scan("出现测试词一次")
    assert [(h["word"], h["category"]) for h in hits] == [("测试词", "catB")]

    # 错位重叠：AB 从 0 开始，BCDE 从 1 开始——先出现者保留，BCDE 被丢弃
    hits = scan("ABCDE")
    assert [(h["word"], h["start"], h["end"]) for h in hits] == [("AB", 0, 2)]


def test_benchmark_10k_chars_under_200ms():
    """一万字扫描多次取均值 < 200ms（任务书性能预算）。"""
    paragraph = "这款产品号称全网最低价，销量第一品牌，效果最好最安全，建议加微信免费领取，远离赌博与刷单。"
    text = (paragraph * 400)[:10000]
    assert len(text) == 10000
    scan(text)  # 预热（含词库加载与正则编译）
    runs = 5
    durations = []
    for _ in range(runs):
        t0 = time.perf_counter()
        scan(text)
        durations.append(time.perf_counter() - t0)
    avg = sum(durations) / len(durations)
    assert avg < 0.2, f"1 万字平均扫描耗时 {avg * 1000:.1f}ms 超出 200ms 预算"


# ── API：POST /content-check/sensitive ─────────────────────────────────


@pytest_asyncio.fixture
async def app():
    app = FastAPI()
    app.include_router(content_check_router)
    return app


@pytest_asyncio.fixture
async def anon_client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def authed_client(app):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, email="writer@example.com")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_endpoint_rejects_anonymous(anon_client):
    """未认证请求 401（防匿名刷大文本）。"""
    resp = await anon_client.post("/content-check/sensitive", json={"text": "正常文稿"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_endpoint_returns_hits_with_offsets(authed_client):
    resp = await authed_client.post("/content-check/sensitive", json={"text": "这是最好的时代，也是赌博的重灾区。"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == len(body["hits"]) == 2
    words = [h["word"] for h in body["hits"]]
    assert words == ["最好", "赌博"]
    for h in body["hits"]:
        assert h["category"] in CATEGORIES
        assert h["severity"] in ("high", "medium", "low")
        assert isinstance(h["start"], int) and isinstance(h["end"], int) and 0 <= h["start"] < h["end"]
    source = "这是最好的时代，也是赌博的重灾区。"
    for h in body["hits"]:
        assert source[h["start"] : h["end"]] == h["word"]


@pytest.mark.asyncio
async def test_endpoint_rejects_empty_text(authed_client):
    resp = await authed_client.post("/content-check/sensitive", json={"text": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_rejects_text_over_20000_chars(authed_client):
    resp = await authed_client.post("/content-check/sensitive", json={"text": "好" * 20001})
    assert resp.status_code == 422
    # 边界内不因长度拒绝（20000 字符本身合法，只验证不报长度 422）
    ok = await authed_client.post("/content-check/sensitive", json={"text": "安" * 20000})
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_endpoint_clean_text_returns_empty(authed_client):
    resp = await authed_client.post("/content-check/sensitive", json={"text": "一篇正常的科普文稿。"})
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "hits": []}
