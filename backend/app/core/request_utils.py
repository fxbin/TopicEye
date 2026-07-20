"""
统一的客户端 IP 提取工具。

历史背景：auth.py / oauth.py / main.py / middleware/rate_limit.py 各自
实现了不同语义的客户端 IP 提取（有的处理 X-Forwarded-For，有的只取
request.client.host），导致安全审计日志与限流桶看到的 IP 在反代场景下
不一致。本模块收敛为单一实现，由 settings.TRUST_FORWARDED_IP 控制
是否信任代理透传头。

@since 2026-07-20
@author fxbin
"""
from __future__ import annotations

from fastapi import Request

from app.core.config import settings


def client_ip(request: Request) -> str:
    """
    从 FastAPI Request 中安全提取客户端 IP。

    行为规则：
    1. 若 settings.TRUST_FORWARDED_IP 为 True 且请求头中存在
       X-Forwarded-For，取其首段（最左侧客户端 IP）作为返回值；
    2. 否则回落到 request.client.host（直连 socket 远端地址）；
    3. 若以上均不可用（如测试场景下 request.client 为 None），返回 "unknown"。

    注意：信任 X-Forwarded-For 的前提是前置反向代理已正确覆写该头部，
    否则客户端可伪造该值绕过限流或污染审计日志。

    :param request: FastAPI Request 实例
    :return: 客户端 IP 字符串，无法判定时返回 "unknown"
    """
    if settings.TRUST_FORWARDED_IP:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            first_hop = forwarded_for.split(",", 1)[0].strip()
            if first_hop:
                return first_hop
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
