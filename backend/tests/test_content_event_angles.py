"""事件切面稀缺度分析（POST /contents/{id}/event/angles）行为测试。

LLM 一律 mock，不调真实模型；沿用 test_content_event_api.py 的
TestClient + dependency_overrides + monkeypatch 模式。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import content_events
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.services import content_event_angles
from app.services.content_event_angles import (
    RAW_CONTENT_MAX_CHARS,
    TOTAL_INPUT_MAX_CHARS,
    EventAngleAnalysisError,
    _build_user_message,
    analyze_event_angles,
)
from app.services.content_event_service import ContentEventNotFoundError
from app.services.llm.budget_guard import LlmBudgetExceededError
from app.services.llm.circuit_breaker import CircuitOpenError


class _Session:
    pass


def _content(
    cid: int,
    *,
    title: str | None = None,
    summary: str | None = None,
    raw: str | None = None,
    published: datetime | None = None,
    owner: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=cid,
        title=title if title is not None else f"报道 {cid}",
        url=f"https://example.test/{cid}",
        summary=summary,
        raw_content=raw,
        published_at=published,
        crawled_at=published,
        created_at=published,
        owner_user_id=owner,
    )


def _group(gid: int = 11, canonical_id: int = 7, version: int = 3) -> SimpleNamespace:
    return SimpleNamespace(id=gid, canonical_content_id=canonical_id, version=version, owner_user_id=None)


def _row(cid: int, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(member=SimpleNamespace(content_id=cid), content=_content(cid, **kwargs))


class _FakeRepo:
    def __init__(self, *, contents: dict, group, member_rows: list):
        self._contents = contents
        self._group = group
        self._member_rows = member_rows

    async def get_content(self, content_id: int, *, for_update: bool = False):
        return self._contents.get(content_id)

    async def resolve_visible_group(self, content_id: int, *, visible_user_id, include_shadow: bool = False):
        return self._group

    async def list_member_rows(self, event_id: int, *, include_unaccepted: bool = True, **kwargs):
        assert include_unaccepted is False, "切面分析必须只取已接受成员"
        return self._member_rows


def _install_service(monkeypatch, *, contents: dict, group, member_rows: list, llm_result=None, llm_error=None):
    """替换 service 模块内的 repository 与 LLM 调用，返回捕获到的调用参数。"""

    captured: dict = {}

    async def fake_llm(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        if llm_error is not None:
            raise llm_error
        return llm_result

    repo = _FakeRepo(contents=contents, group=group, member_rows=member_rows)
    monkeypatch.setattr(content_event_angles, "ContentEventRepository", lambda db: repo)
    monkeypatch.setattr(content_event_angles, "call_llm_json", fake_llm)
    return captured


# ── service 层 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_visible_event_returns_no_event_without_llm_call(monkeypatch):
    content = _content(7, published=datetime(2026, 7, 1, tzinfo=UTC))
    captured = _install_service(
        monkeypatch,
        contents={7: content},
        group=None,
        member_rows=[],
        llm_result={"covered_angles": []},
    )

    result = await analyze_event_angles(object(), 7, visible_user_id=None)

    assert result == {"status": "no_event"}
    assert "messages" not in captured  # 无事件不烧 LLM 调用


@pytest.mark.asyncio
async def test_event_without_accepted_members_returns_no_event(monkeypatch):
    content = _content(7, published=datetime(2026, 7, 1, tzinfo=UTC))
    captured = _install_service(
        monkeypatch,
        contents={7: content},
        group=_group(),
        member_rows=[],
        llm_result={"covered_angles": []},
    )

    result = await analyze_event_angles(object(), 7, visible_user_id=None)

    assert result == {"status": "no_event"}
    assert "messages" not in captured


@pytest.mark.asyncio
async def test_missing_or_invisible_content_raises_not_found(monkeypatch):
    private = _content(7, owner=99, published=datetime(2026, 7, 1, tzinfo=UTC))
    _install_service(monkeypatch, contents={7: private}, group=_group(), member_rows=[_row(8)])

    with pytest.raises(ContentEventNotFoundError):
        await analyze_event_angles(object(), 7, visible_user_id=None)

    _install_service(monkeypatch, contents={}, group=_group(), member_rows=[])
    with pytest.raises(ContentEventNotFoundError):
        await analyze_event_angles(object(), 404, visible_user_id=1)


@pytest.mark.asyncio
async def test_success_path_structure_and_ref_titles(monkeypatch):
    base = datetime(2026, 7, 1, tzinfo=UTC)
    canonical = _content(7, title="主报道", raw="正文七", published=base)
    member_a = _content(8, title="成员八 {ok}", summary="摘要八", raw="正文八", published=base + timedelta(hours=1))
    member_b = _content(9, title="成员九", raw="正文九", published=base + timedelta(hours=2))
    llm_payload = {
        "covered_angles": ["官方通报口径", "发布会时间线", "", "  ", *[f"角度{i}" for i in range(3, 12)]],
        "scarce_angles": [
            {"angle": "受影响用户成本视角", "reason": "列表只覆盖官方口径", "ref_content_ids": [7, 8, 999, "8", 7]},
            {"angle": "无有效引用的角度", "reason": "引用全部是幻觉", "ref_content_ids": [999, "ghost"]},
            {"angle": "供应链影响视角", "reason": "只有一篇提到但未展开", "ref_content_ids": ["9"]},
        ],
        "audience_questions": ["涨价会持续多久？", "", "普通用户现在要囤货吗？"],
    }
    captured = _install_service(
        monkeypatch,
        contents={7: canonical, 8: member_a, 9: member_b},
        group=_group(),
        member_rows=[
            _row(8, title="成员八 {ok}", summary="摘要八", raw="正文八", published=base + timedelta(hours=1)),
            _row(9, title="成员九", raw="正文九", published=base + timedelta(hours=2)),
        ],
        llm_result=llm_payload,
    )

    result = await analyze_event_angles(object(), 7, visible_user_id=None)

    assert result["status"] == "ok"
    assert result["event_id"] == 11 and result["version"] == 3
    assert result["truncated"] is False
    # 空白角度被剔除，且不超过 8 条上限
    assert result["covered_angles"][:3] == ["官方通报口径", "发布会时间线", "角度3"]
    assert len(result["covered_angles"]) == 8
    assert result["audience_questions"] == ["涨价会持续多久？", "普通用户现在要囤货吗？"]

    scarce = result["scarce_angles"]
    assert [item["angle"] for item in scarce] == ["受影响用户成本视角", "供应链影响视角"]
    # 引用防幻觉：只保留输入成员集合内的编号、去重；无有效引用的角度整条丢弃
    assert scarce[0]["refs"] == [
        {"content_id": 7, "title": "主报道"},
        {"content_id": 8, "title": "成员八 {ok}"},
    ]
    assert scarce[1]["refs"] == [{"content_id": 9, "title": "成员九"}]
    # 每条引用带 title
    assert all(ref["title"] for item in scarce for ref in item["refs"])

    # LLM 调用参数与输入拼装
    assert captured["kwargs"] == {"temperature": 0.3, "max_tokens": 2000, "scene": "event_angles"}
    user_content = captured["messages"][1]["content"]
    assert "#7 | 主报道" in user_content
    # sanitize 转义的花括号插入后保持双写（与 angle_recommend 既有行为一致），不参与 format 解析
    assert "#8 | 成员八 {{ok}}" in user_content
    assert len(user_content) <= TOTAL_INPUT_MAX_CHARS


@pytest.mark.asyncio
async def test_member_over_limit_keeps_latest_and_marks_truncated(monkeypatch):
    base = datetime(2026, 7, 1, tzinfo=UTC)
    canonical = _content(1, title="最早主报道", raw="正文一", published=base)
    member_rows = [
        _row(cid, title=f"成员{cid}", raw=f"正文{cid}", published=base + timedelta(hours=cid))
        for cid in range(2, 33)  # 31 篇成员 + canonical = 32 篇
    ]
    contents = {1: canonical, **{row.content.id: row.content for row in member_rows}}
    captured = _install_service(
        monkeypatch,
        contents=contents,
        group=_group(canonical_id=1),
        member_rows=member_rows,
        llm_result={
            "covered_angles": ["a"],
            "scarce_angles": [{"angle": "x", "reason": "r", "ref_content_ids": [32]}],
            "audience_questions": ["q"],
        },
    )

    result = await analyze_event_angles(object(), 1, visible_user_id=None)

    assert result["truncated"] is True
    assert result["analyzed_count"] == 30
    user_content = captured["messages"][1]["content"]
    assert "#32 |" in user_content and "#31 |" in user_content
    # 最新的 30 篇保留，最旧的 canonical(1) 与成员 2 被裁掉
    assert "#1 |" not in user_content and "#2 |" not in user_content
    # 裁掉后仍在输入集合外的引用会被防幻觉过滤丢弃
    assert result["scarce_angles"] == [{"angle": "x", "reason": "r", "refs": [{"content_id": 32, "title": "成员32"}]}]


@pytest.mark.asyncio
async def test_llm_chain_exception_propagates_uncollapsed(monkeypatch):
    content = _content(7, published=datetime(2026, 7, 1, tzinfo=UTC))
    _install_service(
        monkeypatch,
        contents={7: content, 8: _content(8)},
        group=_group(),
        member_rows=[_row(8)],
        llm_error=CircuitOpenError("circuit open"),
    )

    # 不捕获不折叠：LLM 链路异常原样上抛（禁止安静失败）
    with pytest.raises(CircuitOpenError):
        await analyze_event_angles(object(), 7, visible_user_id=None)


@pytest.mark.asyncio
async def test_unparsable_llm_result_raises_instead_of_fake_success(monkeypatch):
    content = _content(7, published=datetime(2026, 7, 1, tzinfo=UTC))
    member_rows = [_row(8)]
    for bad in ({"raw_response": "not json"}, ["not", "a", "dict"], {"unrelated": 1}):
        _install_service(
            monkeypatch,
            contents={7: content, 8: _content(8)},
            group=_group(),
            member_rows=member_rows,
            llm_result=bad,
        )
        with pytest.raises(EventAngleAnalysisError):
            await analyze_event_angles(object(), 7, visible_user_id=None)


def test_build_user_message_truncates_oversized_raw_content():
    article = _content(7, title="主报道", summary="摘要", raw="长" * 50_000)

    message = _build_user_message("事件标题", [article])

    # 单篇超长正文按 sanitize 上限截断，总长度受控且保留截断标记
    assert len(message) < 3_000
    assert "…(truncated)" in message
    assert message.count("长") <= RAW_CONTENT_MAX_CHARS


def test_build_user_message_enforces_total_cap_and_survives_braces():
    articles = [
        _content(
            7, title="标题 {brace}", summary="摘要", raw="字" * 50_000, published=datetime(2026, 7, 1, tzinfo=UTC)
        ),
        _content(8, title="标题二", summary="摘要", raw="文" * 50_000, published=datetime(2026, 7, 2, tzinfo=UTC)),
    ]

    message = _build_user_message("事件标题", articles)

    # 两篇超长正文按篇数均摊收紧预算，user message 不越过硬上限
    assert len(message) <= TOTAL_INPUT_MAX_CHARS
    # 内容里的花括号经 sanitize 转义后插入值不再参与 format 解析，format 不抛错；
    # 转义后的双花括号保留在最终消息里（与 angle_recommend 既有行为一致）
    assert "标题 {{brace}}" in message


# ── API 层 ────────────────────────────────────────────────────────────────


def _client(*, user_id: int = 42) -> TestClient:
    app = FastAPI()
    app.include_router(content_events.router)
    app.dependency_overrides[get_db] = lambda: _Session()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    return TestClient(app)


def test_angles_endpoint_success_shape(monkeypatch):
    calls: list = []

    async def service(db, content_id, **kwargs):
        calls.append((type(db).__name__, content_id, kwargs))
        return {
            "status": "ok",
            "event_id": 11,
            "version": 3,
            "truncated": False,
            "analyzed_count": 3,
            "covered_angles": ["官方通报口径"],
            "scarce_angles": [{"angle": "成本视角", "reason": "r", "refs": [{"content_id": 8, "title": "成员八"}]}],
            "audience_questions": ["会持续多久？"],
        }

    monkeypatch.setattr(content_events, "analyze_event_angles", service)
    response = _client().post("/contents/8/event/angles")

    assert response.status_code == 200
    assert calls == [("_Session", 8, {"visible_user_id": 42})]
    assert response.json() == {
        "status": "ok",
        "event_id": 11,
        "version": 3,
        "truncated": False,
        "analyzed_count": 3,
        "covered_angles": ["官方通报口径"],
        "scarce_angles": [{"angle": "成本视角", "reason": "r", "refs": [{"content_id": 8, "title": "成员八"}]}],
        "audience_questions": ["会持续多久？"],
    }


def test_angles_endpoint_no_event_is_200_with_explicit_status(monkeypatch):
    async def service(db, content_id, **kwargs):
        return {"status": "no_event"}

    monkeypatch.setattr(content_events, "analyze_event_angles", service)
    response = _client().post("/contents/8/event/angles")

    assert response.status_code == 200
    assert response.json()["status"] == "no_event"
    assert response.json()["scarce_angles"] == []


def test_angles_endpoint_maps_not_found_to_404(monkeypatch):
    async def service(db, content_id, **kwargs):
        raise ContentEventNotFoundError("private")

    monkeypatch.setattr(content_events, "analyze_event_angles", service)
    response = _client().post("/contents/404/event/angles")

    assert response.status_code == 404
    assert response.json() == {"detail": "Content not found"}


@pytest.mark.parametrize(
    ("error", "expected_fragment"),
    [
        (CircuitOpenError("open"), "熔断"),
        (LlmBudgetExceededError("no budget"), "预算"),
        (EventAngleAnalysisError("bad shape"), "结构不可用"),
        (RuntimeError("unexpected"), "事件角度分析失败"),
    ],
)
def test_angles_endpoint_maps_llm_failures_to_explicit_502(monkeypatch, error, expected_fragment):
    async def service(db, content_id, **kwargs):
        raise error

    monkeypatch.setattr(content_events, "analyze_event_angles", service)
    response = _client().post("/contents/8/event/angles")

    # 显式失败而非 200 假成功
    assert response.status_code == 502
    assert expected_fragment in response.json()["detail"]
