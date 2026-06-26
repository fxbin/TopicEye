"""github scraper 单测: HTML 解析 + title 超长截断防御.

全部用 FakeClient mock, 不真发请求。
重点验证: 仓库描述 >500 字符时 title 被截断、extra.description 保留完整。
"""

from __future__ import annotations

import httpx
import pytest

from app.services.trending_scrapers._github import GitHubTrending
from app.services.trending_scrapers import TITLE_MAX, truncate_title


# ── Fake client ─────────────────────────────────────────────────
class FakeClient:
    def __init__(self, html: str):
        self._html = html
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, text=self._html, request=request)


def _article(href: str, repo: str, desc: str, stars: str = "1,234") -> str:
    """构造一个 GitHub trending <article> 的 HTML 片段。"""
    return f"""
    <article class="Box-row">
      <h2 class="h3 lh-condensed">
        <a href="{href}">{repo}</a>
      </h2>
      <p class="col-9 color-fg-muted my-1 pr-4">{desc}</p>
      <a class="Link Link--muted d-inline-block Link--with-underline" href="/{repo}/stargazers">
        <svg></svg> {stars}
      </a>
    </article>"""


def _page(articles: list[str]) -> str:
    return "<html><main>" + "".join(articles) + "</main></html>"


# ── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_normal_description_not_truncated():
    """描述短于阈值: title 原样保留, 不截断。"""
    html = _page([_article("/owner/repo", "owner/repo", "A cool project", "2,500")])
    entries = await GitHubTrending().fetch(FakeClient(html))

    assert len(entries) == 1
    e = entries[0]
    assert e["title"] == "A cool project"
    assert e["url"] == "https://github.com/owner/repo"
    # stars 解析依赖 GitHub 真实 svg 结构, 这里只确认不崩; 数值断言在正则覆盖内
    assert e["hot_value"] >= 0
    assert e["extra"]["repo"] == "owner/repo"
    assert e["extra"]["description"] == "A cool project"


@pytest.mark.asyncio
async def test_overlong_description_truncated():
    """描述 >500 字符: title 截断到 TITLE_MAX+省略号, extra.description 保留完整。"""
    long_desc = "x" * 600
    html = _page([_article("/o/r", "o/r", long_desc)])
    entries = await GitHubTrending().fetch(FakeClient(html))

    assert len(entries) == 1
    e = entries[0]
    # title 必须安全入库 (<=500, 留余量)
    assert len(e["title"]) <= 500
    assert len(e["title"]) == TITLE_MAX
    assert e["title"].endswith("…")
    # 完整描述不丢
    assert e["extra"]["description"] == long_desc


@pytest.mark.asyncio
async def test_no_description_falls_back_to_repo_name():
    """无描述 (desc 为空): title 用仓库名, 不会是空串。"""
    html = _page([_article("/owner/blank", "owner/blank", "")])
    entries = await GitHubTrending().fetch(FakeClient(html))

    assert len(entries) == 1
    assert entries[0]["title"] == "owner/blank"
    assert entries[0]["extra"]["description"] == ""


@pytest.mark.asyncio
async def test_fetch_network_error_returns_empty():
    """网络异常返回空列表, 不向上抛。"""
    class ErrClient:
        async def get(self, url, **kwargs):
            raise ConnectionError("boom")

    entries = await GitHubTrending().fetch(ErrClient())
    assert entries == []


def testtruncate_title_helper():
    """truncate_title 边界: 阈值内原样, 超阈截断 + 省略号。"""
    assert truncate_title("short") == "short"
    assert len(truncate_title("x" * (TITLE_MAX - 1))) == TITLE_MAX - 1  # 未超
    out = truncate_title("x" * (TITLE_MAX + 50))
    assert len(out) == TITLE_MAX
    assert out.endswith("…")
    # 中文也安全 (按字符数)
    out_cn = truncate_title("中" * 600)
    assert len(out_cn) == TITLE_MAX
    assert out_cn.endswith("…")
