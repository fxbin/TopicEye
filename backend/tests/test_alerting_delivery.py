"""webhook 告警投递的回归测试。

覆盖 2026-09-05 修复：
- url_preview 曾截取 URL 前 80 字符，飞书/钉钉 token 就在路径里，等于把凭证
  完整写进日志与 webhook_delivery_logs 表；
- 投递曾只发一次，瞬时故障（网络异常 / 5xx / 429）直接丢失告警。
"""

from __future__ import annotations

import pytest

import app.services.alerting as alerting


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class FakeClient:
    """按脚本依次返回响应或抛异常的 httpx.AsyncClient 替身。"""

    def __init__(self, script: list):
        self._script = list(script)
        self.posts = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        self.posts += 1
        if not self._script:
            raise AssertionError("unexpected extra POST")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(alerting, "_WEBHOOK_RETRY_BACKOFF_SECONDS", 0.0)


@pytest.fixture
def captured_records(monkeypatch):
    records: list[dict] = []

    async def fake_persist(**kwargs):
        records.extend(kwargs["records"])

    monkeypatch.setattr(alerting, "_persist_delivery_logs", fake_persist)
    return records


def _wire(monkeypatch, script: list, url: str) -> FakeClient:
    async def fake_resolve(event_type):
        return [url]

    monkeypatch.setattr(alerting, "_resolve_webhook_urls", fake_resolve)
    client = FakeClient(script)
    # 工厂：send_alert 内 `httpx.AsyncClient(timeout=10)` → FakeClient
    monkeypatch.setattr(alerting.httpx, "AsyncClient", lambda timeout=None: client)
    return client


FEISHU_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/0d7a9f1e2b3c4d5e6f7a8b9c"


@pytest.mark.asyncio
async def test_url_preview_masks_token(monkeypatch, captured_records):
    client = _wire(monkeypatch, [FakeResponse(200)], FEISHU_URL)
    ok = await alerting.send_alert(title="t", message="m", alert_key="mask-test")
    assert ok is True
    assert client.posts == 1
    preview = captured_records[0]["webhook_url_preview"]
    assert "0d7a9f1e" not in preview
    assert preview.startswith("https://open.feishu.cn/")
    assert preview.endswith("****")


@pytest.mark.asyncio
async def test_transient_5xx_retries_then_succeeds(monkeypatch, no_sleep, captured_records):
    client = _wire(monkeypatch, [FakeResponse(503), FakeResponse(200)], FEISHU_URL)
    ok = await alerting.send_alert(title="t", message="m", alert_key="retry-5xx")
    assert ok is True
    assert client.posts == 2
    assert captured_records[0]["success"] is True


@pytest.mark.asyncio
async def test_deterministic_4xx_no_retry(monkeypatch, no_sleep, captured_records):
    client = _wire(monkeypatch, [FakeResponse(404, "no such hook")], FEISHU_URL)
    ok = await alerting.send_alert(title="t", message="m", alert_key="retry-404")
    assert ok is False
    assert client.posts == 1, "4xx 是确定性失败，不应重试"
    rec = captured_records[0]
    assert rec["success"] is False
    assert "attempt 1/3" in rec["error_message"]


@pytest.mark.asyncio
async def test_network_errors_retry_until_success(monkeypatch, no_sleep, captured_records):
    client = _wire(
        monkeypatch,
        [ConnectionError("boom"), TimeoutError("t/o"), FakeResponse(200)],
        FEISHU_URL,
    )
    ok = await alerting.send_alert(title="t", message="m", alert_key="retry-net")
    assert ok is True
    assert client.posts == 3


@pytest.mark.asyncio
async def test_all_attempts_exhausted(monkeypatch, no_sleep, captured_records):
    client = _wire(monkeypatch, [FakeResponse(500)] * 3, FEISHU_URL)
    ok = await alerting.send_alert(title="t", message="m", alert_key="retry-exhaust")
    assert ok is False
    assert client.posts == 3, "有界重试上限为 3 次"
    rec = captured_records[0]
    assert rec["success"] is False
    assert rec["status_code"] == 500
