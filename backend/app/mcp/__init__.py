"""MCP server entry layer — expose TopicEye over the Model Context Protocol.

与 ``app/api/v1`` 平级的入口层，遵守同一套分层纪律：只调用 services
（外加与 skill.py 相同的 DailyReportRepository 直查），不直接构造 ORM
查询。传输用 streamable-http（挂载在 ``/mcp``），认证复用站点的
Bearer token 体系（个人 API token / 浏览器 session token）。
"""

from app.mcp.auth import TopicEyeTokenVerifier
from app.mcp.server import build_streamable_http_app, mcp_server

__all__ = ["TopicEyeTokenVerifier", "build_streamable_http_app", "mcp_server"]
