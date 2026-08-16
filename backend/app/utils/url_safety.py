"""共享的 SSRF 防护：判断 URL 主机是否指向内网/保留地址。

article_reader（站内阅读）与 content_pipeline（信源抓取）共用同一套
判定逻辑，避免"一个入口有防护、另一个入口没有"的漂移。
"""

from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """URL 主机指向内网/保留地址（或解析结果如此），禁止服务端代为请求。"""


# 明确禁止的主机名（不含点、无法用 IP 语义判定的内网别名）
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def is_private_address(value: str) -> bool:
    """Return True when *value* parses as a private/loopback/reserved IP."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def hostname_is_blocked(hostname: str | None) -> bool:
    """字面量检查（无 IO）：主机名是内网别名或私网 IP 字面量。

    同时覆盖非点分十进制 IP 记法（如 ``2130706433``、``0x7f000001``），
    防止绕过；``127.1`` 这类省略形式留给抓取层的 DNS 校验兜底。
    """
    host = (hostname or "").rstrip(".").lower()
    if host in _BLOCKED_HOSTNAMES or is_private_address(host):
        return True
    if host.startswith("0x") or host.isdigit():
        try:
            return is_private_address(str(ipaddress.ip_address(int(host, 0))))
        except (ValueError, OverflowError):
            return False
    return False


async def _resolve_host(host: str) -> list[str]:
    """DNS 解析出全部地址；独立成函数便于测试 monkeypatch。"""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    return [info[4][0] for info in infos]


async def ensure_public_hostname(url: str, *, resolve: bool = True) -> None:
    """Raise UnsafeUrlError when *url* points at a private/reserved target.

    先做字面量检查（无 IO）；``resolve=True`` 时再做 DNS 解析检查，
    拦截"稳定解析到内网 IP"的域名（内网域名 / rebinding 常见形态）。
    DNS 解析失败不视为不安全——交给抓取层以常规网络错误处理，
    避免离线环境下误伤。
    """
    host = (urlparse(url).hostname or "").rstrip(".").lower()
    if hostname_is_blocked(host):
        raise UnsafeUrlError(f"URL 主机指向内网或保留地址：{host}")
    if not resolve or not host:
        return
    try:
        addresses = await _resolve_host(host)
    except OSError:
        return
    for address in addresses:
        if is_private_address(address):
            raise UnsafeUrlError(f"URL 主机 {host} 解析到内网或保留地址 {address}")
