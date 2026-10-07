"""TopicEye MCP server — 选题雷达的 Model Context Protocol 入口。

四个工具全部镜像 agent 专用 REST 端点（见 AGENT_API.md），不重复
业务逻辑，只做协议适配（均无破坏性写操作；get_daily_report 缺省分支
会自动生成当日快照）：

  get_today_picks ← GET /api/v1/skill/today-picks
  get_daily_report ← GET /api/v1/skill/daily-report
  get_trends       ← GET /api/v1/skill/trends
  score_items      ← POST /api/v1/scoring/score

传输层选择 ``json_response=True + stateless_http=True``：每个请求返回纯
JSON、无服务端会话，与 2026-07-28 无状态协议形态一致，也绕开了宿主
BaseHTTPMiddleware 对 SSE 长流的潜在缓冲问题。协议版本由 SDK 与客户端
自动协商（2026-07-28 及全部旧修订均可服务）。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import urlparse

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from app.core.config import settings
from app.core.database import async_session
from app.mcp.auth import TopicEyeTokenVerifier
from app.repositories.daily_report_repo import DailyReportRepository
from app.schemas.daily_report import DailyReportResponse
from app.schemas.scoring import ScoringRequestItem
from app.schemas.skill import SkillTodayPicksResponse, SkillTrendsResponse
from app.services import duckdb_service
from app.services.daily_report import get_latest_today_report
from app.services.scoring_engine import (
    build_scoring_response,
    request_item_to_scoring_input,
    score_items as run_score_items,
)
from app.services.today_picks import build_today_picks

logger = logging.getLogger(__name__)


def _base_url() -> str:
    """站点根 URL；未配置时回退本地开发地址（issuer/资源标识仅用于元数据）。"""
    return (settings.SITE_BASE_URL or "http://127.0.0.1:8000").rstrip("/")


def _transport_security() -> TransportSecuritySettings:
    """生产环境按 SITE_BASE_URL 启用 Host/Origin 校验（防 DNS rebinding）。

    开发/测试显式关闭：否则 SDK 对 localhost 部署隐式开启防护（只放行
    127.0.0.1/localhost），经代理/隧道/测试 Host 访问会莫名 421。
    SITE_BASE_URL 缺失时显式告警并保持关闭（不静默降级，见 AGENTS.md
    「禁止安静的失败」）。
    """
    if not settings.is_production:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if not settings.SITE_BASE_URL:
        logger.warning(
            "MCP transport security: SITE_BASE_URL 未配置，DNS rebinding 防护保持关闭；" "生产环境应设置 SITE_BASE_URL"
        )
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    netloc = urlparse(settings.SITE_BASE_URL).netloc
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    # SDK 的 Host 校验只认精确值或 "base:*" 通配；SITE_BASE_URL 不带端口时
    # 补通配条目，避免下游代理显式回写端口（:443 等）导致全线 421。
    allowed_hosts = [netloc, f"{netloc}:*"]
    return TransportSecuritySettings(allowed_hosts=allowed_hosts, allowed_origins=origins)


_base = _base_url()

mcp_server = MCPServer(
    name="TopicEye",
    title="TopicEye 选题雷达",
    description="查询今天值得写的选题：精选 picks、日报、话题趋势，并对内容条目跑六维打分。",
    instructions=(
        "这是 TopicEye 选题雷达的 MCP 入口。典型用法：先 get_today_picks 看今天精选，"
        "再用 get_trends 看近期话题走势，get_daily_report 拿编辑好的日报综述，"
        "score_items 可对自己的候选选题批量打分排序。"
    ),
    version="0.1.0",
    token_verifier=TopicEyeTokenVerifier(),
    auth=AuthSettings(
        issuer_url=_base,
        resource_server_url=f"{_base}/mcp",
        required_scopes=[],
        validate_token_resource=False,
    ),
    subscriptions=False,
)


def build_streamable_http_app():
    """构建可挂载到 FastAPI 的 streamable-http ASGI 子应用。

    必须先调用本函数（或 ``mcp_server.streamable_http_app(...)``），
    ``mcp_server.session_manager`` 才可用；宿主 lifespan 里要进入
    ``mcp_server.session_manager.run()``（mount 的子应用 lifespan 不会执行）。
    """
    return mcp_server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security(),
    )


@asynccontextmanager
async def _db_session():
    """每次工具调用一个独立 session；成功 commit、异常 rollback（对齐 get_db）。"""
    async with async_session() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


def _caller_user_id() -> int:
    """从 bearer 认证上下文取调用者 user.id；未认证时抛 ToolError。"""
    access_token = get_access_token()
    if access_token is None:
        # 理论上到不了这里（认证中间件已拦截），保底防御
        raise ToolError("MCP 工具调用需要 Bearer token 认证")
    client_id = str(access_token.client_id)
    if not client_id.isdigit():
        raise ToolError(f"无效的 token 主体: {client_id!r}")
    return int(client_id)


@mcp_server.tool(
    name="get_today_picks",
    title="今日精选选题",
    description=(
        "返回最近 N 小时 TopicEye 的精选选题，含每条的评分明细"
        "（adjusted_curation_score / score_breakdown）。用于回答「今天有什么值得写的」。"
    ),
)
async def get_today_picks(
    hours: Annotated[int, Field(ge=1, le=168, description="回看时间窗（小时）")] = 48,
    limit: Annotated[int, Field(ge=1, le=100, description="返回条数上限")] = 20,
    category: str | None = None,
) -> dict[str, Any]:
    _caller_user_id()
    async with _db_session() as db:
        payload = await build_today_picks(db, category=category, hours=hours, limit=limit)
    return SkillTodayPicksResponse(**payload).model_dump(mode="json")


@mcp_server.tool(
    name="get_daily_report",
    title="选题日报",
    description=(
        "返回指定日期的选题日报（overview 综述 / top_picks / keywords / trends）；"
        "不传 date 返回今天的最新日报（无则自动生成快照）。日报按 token 所属用户读取。"
    ),
)
async def get_daily_report(
    date: Annotated[str | None, Field(description="YYYY-MM-DD，缺省=今天")] = None,
) -> dict[str, Any]:
    user_id = _caller_user_id()
    async with _db_session() as db:
        if date:
            report = await DailyReportRepository(db).get_by_date(date, owner_user_id=user_id)
            if report is None:
                raise ToolError(f"No report found for {date}")
        else:
            report = await get_latest_today_report(db, owner_user_id=user_id)
    return DailyReportResponse.model_validate(report).model_dump(mode="json")


@mcp_server.tool(
    name="get_trends",
    title="话题趋势 + 关键词",
    description=(
        "合并返回近期话题趋势（topics，按 best_score 排序）与关键词词频（keywords）。"
        "数据来自 DuckDB 分析层的每日快照；分析层不可用时返回错误。"
    ),
)
async def get_trends(
    days: Annotated[int, Field(ge=1, le=30, description="回看天数")] = 7,
    limit: Annotated[int, Field(ge=10, le=200, description="关键词返回上限")] = 50,
) -> dict[str, Any]:
    _caller_user_id()
    try:
        topics = await duckdb_service.run_query(lambda: duckdb_service.query_trend_topics(days=days))
        keywords = await duckdb_service.run_query(lambda: duckdb_service.query_keyword_cloud(days=days, limit=limit))
    except Exception as exc:
        logger.exception("MCP get_trends DuckDB query failed")
        raise ToolError("DuckDB analytical layer unavailable") from exc
    return SkillTrendsResponse(days=days, topics=topics, keywords=keywords).model_dump(mode="json")


@mcp_server.tool(
    name="score_items",
    title="内容六维打分",
    description=(
        "把 1-50 条候选内容跑完整六维打分管线（信息密度/可操作性/创作者价值/爆文潜力/"
        "来源权威/新鲜度加权 + 质量门控 + 风险过滤 + 时间衰减 + 多样性惩罚），"
        "返回每条的完整评分明细。risk_score > 82 的条目会被硬排除。"
        "用于给自己的候选选题排序、解释为什么某条内容得分高。"
    ),
)
async def score_items(
    items: Annotated[list[ScoringRequestItem], Field(min_length=1, max_length=50, description="待打分条目，1-50 条")],
) -> dict[str, Any]:
    _caller_user_id()
    inputs = [request_item_to_scoring_input(item) for item in items]
    scored = run_score_items(inputs)
    return build_scoring_response(scored).model_dump(mode="json")
