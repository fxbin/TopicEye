"""嵌入画布复用原大盘实现，避免再次产生一套监控口径。"""

import pytest

from app.api.dashboard import _DASHBOARD_HTML, embedded_dashboard, router


@pytest.mark.asyncio
async def test_embedded_dashboard_keeps_shared_canvas_and_compact_navigation():
    html = (await embedded_dashboard()).body.decode()
    assert 'data-dashboard="embedded"' in html
    assert 'body.embedded .rail-nav{flex-direction:row' in html
    assert 'body.embedded .rail-brand,body.embedded .rail-caption,body.embedded .rail-foot{display:none}' in html
    # 数据逻辑保持原样，没有在 Next 侧复制图表和阈值。
    assert html.split('<script>', 1)[1] == _DASHBOARD_HTML.split('<script>', 1)[1]
    for tab in ('overview', 'llm-logs', 'app-logs', 'web-vitals'):
        assert f'data-tab="{tab}"' in html


def test_embedded_dashboard_requires_same_admin_dependency():
    original = next(r for r in router.routes if r.path == '/dashboard')
    embedded = next(r for r in router.routes if r.path == '/api/v1/metrics/dashboard')
    assert [d.call for d in embedded.dependant.dependencies] == [d.call for d in original.dependant.dependencies]
    assert embedded.dependant.dependencies
