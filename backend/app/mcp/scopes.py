"""MCP 工具 scope 中央闸门 — 缺省拒绝（fail-closed）。

单一事实源：``TOOL_REQUIRED_SCOPES`` 登记每个 MCP 工具所需的 scope 集。
调用点在 ``app/mcp/server.py`` 每个工具入口（``_enforce_tool_scopes``），
``require_tool_access`` 是唯一的判定函数：

- 工具**未登记** → 直接拒绝（新工具不声明 scope 就上不了线）；
- 已登记 → required ⊆ granted 才放行。

当前四个工具全只读，required 均为空集（存量静态 token 与 OAuth token
的 scopes 都是 []，行为不变）。首个**写操作**工具立项时必须在此登记
真实 scope 语义——CI 断言 ``test_every_tool_registered_in_scope_gate``
保证「工具集与登记集一致」，漏登记过不了门（issue #118 前置 DoD）。
"""

from __future__ import annotations

from collections.abc import Iterable

from mcp.server.mcpserver.exceptions import ToolError

#: 工具名 → 所需 scope 集。默认全部空集（只读，无 scope 要求）；
#: 「默认空」即圆桌裁定的闸门初始形态：结构就位、语义待写工具填入。
TOOL_REQUIRED_SCOPES: dict[str, frozenset[str]] = {
    "get_today_picks": frozenset(),
    "get_daily_report": frozenset(),
    "get_trends": frozenset(),
    "score_items": frozenset(),
}


def require_tool_access(tool_name: str, granted_scopes: Iterable[str]) -> None:
    """缺省拒绝的工具级 scope 判定；不满足抛 ToolError（客户端可见）。"""
    required = TOOL_REQUIRED_SCOPES.get(tool_name)
    if required is None:
        raise ToolError(f"Tool {tool_name!r} is not registered in the MCP scope gate")
    missing = required - set(granted_scopes)
    if missing:
        raise ToolError(f"Missing required scope(s): {' '.join(sorted(missing))}")
