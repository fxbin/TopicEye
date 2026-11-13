"""文稿「去 AI 味」改写建议（service 纯函数 + LLM 编排 + POST /content-check/humanize-rewrite）测试。

覆盖（对应任务书验收）：
1. 选句纯函数：命中数 ≥2 优先、不足 3 句用命中数 =1 的句子补足、同命中数按
   原文顺序、上限 3 句、零命中返回空；
2. 逐句重扫与全扫等价：句末标点属 _SEPARATOR_RE 掩码，词命中不可能跨句界
   （逐句重扫的词频合计与全扫一致，含同词跨句出现）；
3. 成功路径：hit_words ⊆ 该句真实命中（LLM 编造词被过滤）、original 以服务端
   选取句为准（回显错配条目被丢弃）、rewritten 逐字透传（数字不被管道改动）、
   prompt 含「不改事实与数字」指令且全文不进 prompt；
4. LLM 异常注入 → 502；选句为空 → 422 显式原因；未登录 401；超长 20001 → 422。

测试命令：一次性 PG 单跑（conftest 的 autouse fixture 需要 PG），如
bash backend/scripts/test_full_local.sh（实际执行全量 tests/ 套件）。
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.auth import get_current_user
from app.api.v1.content_check import router as content_check_router
from app.services import humanize_rewrite_service as svc
from app.services.ai_trace_service import scan_words, split_sentences
from app.services.humanize_rewrite_service import (
    HumanizeRewriteNoTargetError,
    HumanizeRewriteUnavailableError,
    generate_humanize_rewrites,
    select_target_sentences,
)
from app.services.llm.budget_guard import LlmBudgetExceededError
from app.services.llm.circuit_breaker import CircuitOpenError
from app.services.llm.provider import LlmCapacityUnavailableError, LlmContextWindowExceededError

# 密集 AI 套话样文（同 test_ai_traces.DENSE_TEXT，逐句命中数 [1, 3, 3, 8]，
# 已对真实词库核实：S4=首先/对齐/其次/沉淀/方法论/最后/复用/打法）
DENSE_TEXT = (
    "在流量红利见顶的今天，品牌必须找到新的增长抓手。"
    "我们以用户为中心重构底层逻辑，通过私域运营形成增长闭环。"
    "这套组合拳能够有效赋能创作者，显著提升转化效率。"
    "首先对齐目标，其次沉淀方法论，最后形成可复用的打法。"
)

# 口语化样文：零命中（选句为空 → 422 的口径基础）
COLLOQUIAL_TEXT = (
    "今天下楼吃了一碗牛肉面，老板还是给我多加了一勺辣油。"
    "爽。"
    "吃完顺着河边遛了半小时弯儿，风一吹整个人都清醒了，回家倒头睡了个午觉，猫窝在我脚边也睡着了。"
)

# 构造样文（命中数已对真实词库核实）：A=0（含数字）、B=8、C=2（含数字
# 3 个月/40%）、D=1、E=2。常量按 split_sentences 的返回口径定义（句末标点被
# 去掉），拼接时补回句号。
SENTENCE_A = "这个做法帮我在 3 天里涨了 5000 个粉丝"
SENTENCE_B = "首先对齐目标，其次沉淀方法论，最后形成可复用的打法"
SENTENCE_C = "这套组合拳能够有效赋能创作者，3 个月内转化率提升了 40%"
SENTENCE_D = "我们必须找到新的增长抓手"
SENTENCE_E = "围绕底层逻辑跑出一个增长闭环"

MIXED_TEXT = "。".join([SENTENCE_A, SENTENCE_B, SENTENCE_C, SENTENCE_D, SENTENCE_E]) + "。"


def _real_hit_words(sentence: str) -> list[str]:
    return [h["word"] for h in scan_words(sentence)]


def _install_llm(monkeypatch, *, llm_result=None, llm_error=None) -> dict:
    """替换 service 模块内的 call_llm_json，返回捕获到的调用参数（模式同 test_content_event_angles）。"""

    captured: dict = {}

    async def fake_llm(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        if llm_error is not None:
            raise llm_error
        return llm_result

    monkeypatch.setattr(svc, "call_llm_json", fake_llm)
    return captured


# ── Service：选句纯函数 ─────────────────────────────────────────────────


def test_select_prefers_dense_hits_and_keeps_original_order_on_tie():
    """命中数降序：B(8) → C(2) → E(2)（同命中数按原文顺序）；A(0)/D(1) 不入前三。"""
    assert select_target_sentences(MIXED_TEXT) == [SENTENCE_B, SENTENCE_C, SENTENCE_E]


def test_select_caps_at_three_sentences():
    """上限 3 句：密集样文逐句命中 [1, 3, 3, 8]，选 S4 → S2 → S3。"""
    sentences = split_sentences(DENSE_TEXT)
    selected = select_target_sentences(DENSE_TEXT)
    assert len(selected) == 3
    assert selected == [sentences[3], sentences[1], sentences[2]]  # 8 命中句优先，3 命中句按原文顺序


def test_select_pads_with_single_hit_sentences_when_fewer_dense():
    """不足 3 句时用命中数 =1 的句子补足；句数再少就有多少返回多少。"""
    assert select_target_sentences(SENTENCE_B + "。" + SENTENCE_D) == [SENTENCE_B, SENTENCE_D]
    assert select_target_sentences(SENTENCE_D) == [SENTENCE_D]


def test_select_returns_empty_for_zero_hit_text():
    """零命中句不入选：口语化样文返回空列表（API 据此 422）。"""
    assert select_target_sentences(COLLOQUIAL_TEXT) == []
    assert select_target_sentences("") == []


def test_per_sentence_rescan_equals_full_scan():
    """逐句重扫与全扫等价：词命中不可能跨句界（句末标点是掩码分隔符）。

    逐句重扫的词频合计与全扫一致；样文刻意让同一词跨句出现（赋能×2、抓手×2），
    等价性不是逐句互不重叠的偶然结果。
    """
    text = "。".join([SENTENCE_C, SENTENCE_D, SENTENCE_E, SENTENCE_D, SENTENCE_C]) + "。"
    full_counter = Counter(h["word"] for h in scan_words(text))
    per_sentence_counter: Counter[str] = Counter()
    for sentence in split_sentences(text):
        per_sentence_counter.update(h["word"] for h in scan_words(sentence))
    assert full_counter == per_sentence_counter
    assert full_counter["赋能"] == 2 and full_counter["抓手"] == 2  # 同词跨句，等价性有实质内容


# ── Service：LLM 编排与响应校验 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_success_filters_hit_words_and_preserves_text_verbatim(monkeypatch):
    """成功路径：hit_words 只留真实命中、original=服务端选取句、rewritten 逐字透传。"""
    captured = _install_llm(
        monkeypatch,
        llm_result={
            "suggestions": [
                # 编造词「降本增效」不在 B 句真实命中里，必须被过滤掉
                {
                    "original": SENTENCE_B,
                    "rewritten": "先定目标，再把能反复用的做法整理出来。",
                    "hit_words": ["方法论", "降本增效", "打法"],
                },
                # hit_words 回显为空：徽标退回该句真实命中，不编造也不空着
                {
                    "original": SENTENCE_C,
                    "rewritten": "这套做法真能帮创作者用起来，3 个月内转化率提升了 40%。",
                    "hit_words": [],
                },
                # 回显与选取句对不上：整条丢弃，不用 LLM 的句子冒充原句
                {"original": "完全没出现过的句子。", "rewritten": "随便改写", "hit_words": ["赋能"]},
            ]
        },
    )

    result = await generate_humanize_rewrites(SENTENCE_A + "。" + SENTENCE_B + "。" + SENTENCE_C + "。")

    assert [s["original"] for s in result["suggestions"]] == [SENTENCE_B, SENTENCE_C]
    first, second = result["suggestions"]
    assert first["hit_words"] == [w for w in ("方法论", "打法") if w in _real_hit_words(SENTENCE_B)]
    assert "降本增效" not in first["hit_words"]
    assert second["hit_words"] == _real_hit_words(SENTENCE_C)
    # 响应管道不改动文本：含数字的改写句逐字保留（「3 个月」「40%」原样到达前端）
    assert second["rewritten"] == "这套做法真能帮创作者用起来，3 个月内转化率提升了 40%。"

    # 调用参数：scene 与低温/收紧的 token 上限
    assert captured["kwargs"]["scene"] == "humanize_rewrite"
    assert captured["kwargs"]["temperature"] <= 0.4
    assert captured["kwargs"]["max_tokens"] <= 1200


@pytest.mark.asyncio
async def test_generate_prompt_contains_fact_guard_and_never_includes_full_text(monkeypatch):
    """prompt 合同：system 含不改事实/数字指令；只有选取句进 prompt，全文与其余句子不进。"""
    text = MIXED_TEXT
    captured = _install_llm(
        monkeypatch,
        llm_result={"suggestions": [{"original": SENTENCE_B, "rewritten": "改写。", "hit_words": []}]},
    )

    await generate_humanize_rewrites(text)

    system_content = captured["messages"][0]["content"]
    user_content = captured["messages"][1]["content"]
    assert captured["messages"][0]["role"] == "system"
    assert "事实" in system_content and "数字" in system_content  # 不改事实与数字的显式指令
    assert SENTENCE_B in user_content and SENTENCE_C in user_content  # 只有选取句进 prompt
    assert SENTENCE_A not in user_content  # 零命中句不进
    assert SENTENCE_D not in user_content  # 落选的低命中句不进
    assert text not in user_content  # 全文永不进 prompt


@pytest.mark.asyncio
async def test_generate_without_hits_raises_before_any_llm_call(monkeypatch):
    """零命中文稿：先抛 422 业务异常，不烧任何 LLM 调用。"""
    captured = _install_llm(monkeypatch, llm_result={"suggestions": []})
    with pytest.raises(HumanizeRewriteNoTargetError):
        await generate_humanize_rewrites(COLLOQUIAL_TEXT)
    assert "messages" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "llm_result",
    [
        {"raw_response": "not-json"},  # 不可解析输出（provider 解析失败合同）
        {"suggestions": "not-a-list"},
        {"suggestions": [{"original": "不存在的句子", "rewritten": "改写"}]},  # 全部回显错配
        {"suggestions": [{"original": SENTENCE_B, "rewritten": "   "}]},  # rewritten 空
    ],
)
async def test_generate_raises_unavailable_when_no_valid_entries(monkeypatch, llm_result):
    """没有任何有效条目 → 业务异常（API 映射 502），不返回空建议装成功。"""
    _install_llm(monkeypatch, llm_result=llm_result)
    with pytest.raises(HumanizeRewriteUnavailableError):
        await generate_humanize_rewrites(SENTENCE_B)


# ── API：POST /content-check/humanize-rewrite ──────────────────────────


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
    """未认证请求 401（与 sensitive/ai-traces 同口径）。"""
    resp = await anon_client.post("/content-check/humanize-rewrite", json={"text": DENSE_TEXT})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_endpoint_returns_suggestions_from_server_selected_sentences(monkeypatch, authed_client):
    """成功路径：≤3 条建议，original 全部来自服务端选取句，hit_words ⊆ 该句真实命中。"""
    selected = select_target_sentences(DENSE_TEXT)
    llm_result = {
        "suggestions": [
            {
                "original": sentence,
                "rewritten": f"口语化改写 {i}：保留 3 个方法与 40% 的数字。",
                "hit_words": ["编造的词"] + _real_hit_words(sentence)[:1],
            }
            for i, sentence in enumerate(selected)
        ]
    }
    _install_llm(monkeypatch, llm_result=llm_result)

    resp = await authed_client.post("/content-check/humanize-rewrite", json={"text": DENSE_TEXT})

    assert resp.status_code == 200
    suggestions = resp.json()["suggestions"]
    assert 1 <= len(suggestions) <= 3
    assert [s["original"] for s in suggestions] == selected  # 服务端选取顺序
    for suggestion in suggestions:
        assert suggestion["hit_words"]  # 过滤后仍非空（退回真实命中）
        assert set(suggestion["hit_words"]) <= set(_real_hit_words(suggestion["original"]))
        assert "3 个方法" in suggestion["rewritten"] and "40%" in suggestion["rewritten"]


@pytest.mark.asyncio
async def test_endpoint_no_hit_sentences_returns_422_with_reason(monkeypatch, authed_client):
    """零命中文稿 → 422 且 detail 说明原因（不是静默空建议）。"""
    _install_llm(monkeypatch, llm_result={"suggestions": []})
    resp = await authed_client.post("/content-check/humanize-rewrite", json={"text": COLLOQUIAL_TEXT})
    assert resp.status_code == 422
    assert "命中" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "llm_error,expected_detail",
    [
        (CircuitOpenError("circuit open"), "熔断"),
        (LlmCapacityUnavailableError(routing_group="default", next_available_at=None), "暂不可用"),
        (LlmBudgetExceededError("over budget"), "预算"),
        (LlmContextWindowExceededError("too long"), "上下文"),
        # 末路异常兜底（评审 C-1）：超时/候选耗尽不落 500 英文裸错
        (RuntimeError("unexpected"), "改写建议生成失败，请稍后重试"),
    ],
)
async def test_endpoint_maps_llm_chain_errors_to_502(monkeypatch, authed_client, llm_error, expected_detail):
    """LLM 链路异常 → 502 显式中文文案，不折叠成 200 假成功。"""
    _install_llm(monkeypatch, llm_error=llm_error)
    resp = await authed_client.post("/content-check/humanize-rewrite", json={"text": DENSE_TEXT})
    assert resp.status_code == 502
    assert expected_detail in resp.json()["detail"]


@pytest.mark.asyncio
async def test_endpoint_maps_unparsable_output_to_502(monkeypatch, authed_client):
    """不可解析输出 → 502「结构不可用」。"""
    _install_llm(monkeypatch, llm_result={"raw_response": "not-json"})
    resp = await authed_client.post("/content-check/humanize-rewrite", json={"text": DENSE_TEXT})
    assert resp.status_code == 502
    assert "结构不可用" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_endpoint_rejects_empty_and_overlong_text(authed_client):
    """长度口径与 sensitive/ai-traces 一致：空文本、20001 字 → 422。"""
    empty = await authed_client.post("/content-check/humanize-rewrite", json={"text": ""})
    assert empty.status_code == 422
    over = await authed_client.post("/content-check/humanize-rewrite", json={"text": "好" * 20001})
    assert over.status_code == 422
