"""AI 痕迹启发式统计（service 纯函数）与 POST /content-check/ai-traces（入口层）测试。

覆盖（对应任务书验收）：
1. 内置词表零跳过且在预算区间：buzzword 100~200 条、connective 30~50 条，
   词条不含分隔符、无重复（「禁止安静失败」的机器化）；
2. 密集 AI 套话样文命中并返回 codepoint 偏移，source[start:end]==word，含 emoji；
3. 口语化短句样文分档 low；三子指标分档边界（密度与 CV 阈值等值行为）；
4. 句数 <3 返回 insufficient，不编造分档（词证据充分时除外）；
5. 未认证 401、空文本 422、超长 422（与 sensitive 同口径）；
6. 一万字统计多次取均值 < 500ms。

测试命令：一次性 PG 单跑（conftest 的 autouse fixture 需要 PG），如
bash backend/scripts/test_full_local.sh 迭代期可自起一次性 PG 后
DATABASE_URL=postgresql+asyncpg://... python -m pytest tests/test_ai_traces.py
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
from app.core.ai_traces import (
    DIMENSION_BUZZWORD,
    DIMENSION_CONNECTIVE,
    LEVEL_HIGH,
    LEVEL_INSUFFICIENT,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    LEVELS,
)
from app.services import ai_trace_service as svc
from app.services.ai_trace_service import analyze, load_lexicon

# 密集 AI 套话样文：黑话 + 首先/其次/最后 模板结构 + 句长均匀
DENSE_TEXT = (
    "在流量红利见顶的今天，品牌必须找到新的增长抓手。"
    "我们以用户为中心重构底层逻辑，通过私域运营形成增长闭环。"
    "这套组合拳能够有效赋能创作者，显著提升转化效率。"
    "首先对齐目标，其次沉淀方法论，最后形成可复用的打法。"
)

# 口语化样文：零黑话零套话连接词，句长长短交错（25/1/45）
COLLOQUIAL_TEXT = (
    "今天下楼吃了一碗牛肉面，老板还是给我多加了一勺辣油。"
    "爽。"
    "吃完顺着河边遛了半小时弯儿，风一吹整个人都清醒了，回家倒头睡了个午觉，猫窝在我脚边也睡着了。"
)

# ── Service：词表与纯函数 ────────────────────────────────────────────────


def test_builtin_lexicons_all_valid_and_within_size_budget():
    """内置词表零跳过：词条非空、不含分隔符、无重复；数量在预算区间。"""
    buzz = load_lexicon(DIMENSION_BUZZWORD)
    conn = load_lexicon(DIMENSION_CONNECTIVE)
    assert 100 <= len(buzz) <= 200, f"buzzword 词量超出预算: {len(buzz)}"
    assert 30 <= len(conn) <= 50, f"connective 词量超出预算: {len(conn)}"
    for dimension, words in ((DIMENSION_BUZZWORD, buzz), (DIMENSION_CONNECTIVE, conn)):
        for word in words:
            assert word, f"{dimension} 存在空词条"
            assert not svc._SEPARATOR_RE.search(word), f"{dimension} 词条含空白/标点，会被加载校验跳过: {word!r}"
        assert len(set(words)) == len(words), f"{dimension} 存在重复词条"


def test_dense_buzzword_text_hits_with_sliceable_offsets():
    """密集 AI 套话样文：命中逐词带 codepoint 偏移，可用原文切片还原。"""
    report = analyze(DENSE_TEXT)
    words = [h["word"] for h in report["hits"]]
    for expected in ("抓手", "底层逻辑", "闭环", "组合拳", "赋能", "显著提升", "对齐", "沉淀", "方法论", "打法"):
        assert expected in words, f"样文未命中 {expected}"
    for expected in ("首先", "其次", "最后"):
        assert expected in words
    for hit in report["hits"]:
        assert DENSE_TEXT[hit["start"] : hit["end"]] == hit["word"]
        assert hit["dimension"] in (DIMENSION_BUZZWORD, DIMENSION_CONNECTIVE)
    # 区间两两不交且 start 升序（前端高亮合同）
    for prev, cur in zip(report["hits"], report["hits"][1:], strict=False):
        assert prev["start"] < cur["start"]
        assert prev["end"] <= cur["start"]


def test_offsets_are_original_codepoint_coordinates_with_emoji():
    """emoji 场景偏移不漂移：😀 各占 1 个 codepoint。"""
    text = "😀😀首先，我们要赋能创作者。"
    report = analyze(text)
    hits = {(h["word"], h["start"], h["end"]) for h in report["hits"]}
    assert ("首先", 2, 4) in hits
    assert ("赋能", 8, 10) in hits
    for hit in report["hits"]:
        assert text[hit["start"] : hit["end"]] == hit["word"]


def test_no_word_match_across_punctuation_or_whitespace():
    """标点与空白是分隔符：不得跨标点命中（同敏感词合同）。"""
    assert [h["word"] for h in svc.scan_words("底。层逻辑")] == []
    assert [h["word"] for h in svc.scan_words("赋 能")] == []


def test_colloquial_text_is_low():
    """口语化短句样文：三子指标与总分档均为 low。"""
    report = analyze(COLLOQUIAL_TEXT)
    assert report["level"] == LEVEL_LOW
    assert report["buzzword"]["level"] == LEVEL_LOW
    assert report["connective"]["level"] == LEVEL_LOW
    assert report["rhythm"]["level"] == LEVEL_LOW
    assert report["hits"] == []


def test_density_band_boundaries():
    """密度分档边界：等值进高档判定（≥），阈值下方逐级回落。"""
    band = svc._band_from_density
    for medium_at, high_at in (
        (svc.BUZZWORD_DENSITY_MEDIUM, svc.BUZZWORD_DENSITY_HIGH),
        (svc.CONNECTIVE_DENSITY_MEDIUM, svc.CONNECTIVE_DENSITY_HIGH),
    ):
        assert band(high_at, medium_at, high_at) == LEVEL_HIGH
        assert band(high_at - 0.001, medium_at, high_at) == LEVEL_MEDIUM
        assert band(medium_at, medium_at, high_at) == LEVEL_MEDIUM
        assert band(medium_at - 0.001, medium_at, high_at) == LEVEL_LOW
        assert band(0.0, medium_at, high_at) == LEVEL_LOW


def test_rhythm_band_boundaries():
    """句式均匀度分档边界：CV 等值行为与极端样本。"""
    assert svc._band_from_cv(svc.RHYTHM_CV_HIGH) == LEVEL_MEDIUM  # CV=0.20 等值 → medium
    assert svc._band_from_cv(svc.RHYTHM_CV_HIGH - 1e-9) == LEVEL_HIGH
    assert svc._band_from_cv(svc.RHYTHM_CV_LOW) == LEVEL_LOW  # CV=0.35 等值 → low
    assert svc._band_from_cv(svc.RHYTHM_CV_LOW - 1e-9) == LEVEL_MEDIUM
    # 句长完全一致 → CV=0 → high；长短交错 → low
    assert svc.analyze_rhythm(["十二三四五六七", "十二三四五六七", "十二三四五六七"])["level"] == LEVEL_HIGH
    assert (
        svc.analyze_rhythm(["一二三四五六七八九十一二三四五六七", "一", "一二三四五六七八九十一二三四五六七八九"])[
            "level"
        ]
        == LEVEL_LOW
    )
    # 端到端：密集样文句长均匀（CV<0.20）→ rhythm high
    assert analyze(DENSE_TEXT)["rhythm"]["level"] == LEVEL_HIGH


def test_insufficient_when_fewer_than_three_sentences():
    """句数 <3：rhythm 返回 insufficient 且 cv=null，不编造分档。"""
    report = analyze("赋能抓手闭环。")  # 1 句，但词证据密集
    assert report["rhythm"]["level"] == LEVEL_INSUFFICIENT
    assert report["rhythm"]["cv"] is None
    assert report["rhythm"]["sentence_count"] == 1
    # 词命中仍参与分档：短文本密集黑话照样判 high，不因句少整体弃判
    assert report["buzzword"]["hits"] == 3
    assert report["level"] == LEVEL_HIGH

    # 句少且零命中：无任何可信信号，整体 insufficient 而非编造「痕迹少」
    empty_report = analyze("好的。")
    assert empty_report["level"] == LEVEL_INSUFFICIENT
    assert "不足" in empty_report["advice"]

    # 恰好 3 句可判
    assert svc.analyze_rhythm(["一句", "一句", "一句"])["level"] != LEVEL_INSUFFICIENT


def test_advice_mentions_heuristic_caliber():
    """综合建议必须明示启发式统计口径，且不出现模型检测类措辞。"""
    for text in (DENSE_TEXT, COLLOQUIAL_TEXT, "好的。", "首先赋能，其次沉淀，最后闭环，形成打法。"):
        advice = analyze(text)["advice"]
        assert "启发式统计" in advice
        for banned in ("AI 率", "AI率", "概率", "检测模型"):
            assert banned not in advice


def test_benchmark_10k_chars_under_500ms():
    """一万字统计多次取均值 < 500ms（词扫描 + 分句 + CV，全链路预算）。"""
    paragraph = DENSE_TEXT + COLLOQUIAL_TEXT
    text = (paragraph * 60)[:10000]
    assert len(text) == 10000
    analyze(text)  # 预热（含词表加载与正则编译）
    durations = []
    for _ in range(5):
        t0 = time.perf_counter()
        analyze(text)
        durations.append(time.perf_counter() - t0)
    avg = sum(durations) / len(durations)
    assert avg < 0.5, f"1 万字平均统计耗时 {avg * 1000:.1f}ms 超出 500ms 预算"


# ── API：POST /content-check/ai-traces ─────────────────────────────────


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
async def test_ai_traces_endpoint_rejects_anonymous(anon_client):
    """未认证请求 401（与 sensitive 同口径，防匿名刷大文本）。"""
    resp = await anon_client.post("/content-check/ai-traces", json={"text": "正常文稿"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ai_traces_endpoint_returns_report_with_offsets(authed_client):
    resp = await authed_client.post("/content-check/ai-traces", json={"text": DENSE_TEXT})
    assert resp.status_code == 200
    body = resp.json()
    assert body["level"] in LEVELS
    assert body["character_count"] == len(DENSE_TEXT)
    for key in ("buzzword", "connective"):
        stat = body[key]
        assert stat["dimension"] == key
        assert stat["hits"] > 0 and stat["density_per_kilochar"] > 0
        assert stat["level"] in LEVELS
    assert body["rhythm"]["sentence_count"] == 4
    assert body["rhythm"]["cv"] is not None
    assert "启发式统计" in body["advice"]
    assert body["buzzword"]["hits"] + body["connective"]["hits"] == len(body["hits"])
    for hit in body["hits"]:
        assert DENSE_TEXT[hit["start"] : hit["end"]] == hit["word"]


@pytest.mark.asyncio
async def test_ai_traces_endpoint_rejects_empty_and_overlong_text(authed_client):
    empty = await authed_client.post("/content-check/ai-traces", json={"text": ""})
    assert empty.status_code == 422
    over = await authed_client.post("/content-check/ai-traces", json={"text": "好" * 20001})
    assert over.status_code == 422
    # 边界内不因长度拒绝（无标点长文本 rhythm 判 insufficient，属合法响应）
    ok = await authed_client.post("/content-check/ai-traces", json={"text": "安" * 20000})
    assert ok.status_code == 200
    assert ok.json()["rhythm"]["level"] == LEVEL_INSUFFICIENT
    assert ok.json()["level"] == LEVEL_INSUFFICIENT
