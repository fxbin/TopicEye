import { NextRequest, NextResponse } from 'next/server';

/**
 * 翻译代理路由 — 绕过 Next.js rewrites 的 30s proxyTimeout 限制。
 *
 * LLM 翻译调用可能耗时 15–60s，超过 Next.js 内置 http-proxy 的 30s
 * proxyTimeout 后连接被截断，前端收到 500 Internal Server Error。
 * 此路由用 fetch（无 30s 限制）手动代理到后端，并设 120s AbortController
 * 作为安全上限。
 */
const BACKEND_API_URL = process.env.BACKEND_API_URL || 'http://127.0.0.1:8102';
const PROXY_TIMEOUT_MS = 120_000; // 120s 安全上限

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await ctx.params;
    const authHeader = req.headers.get('authorization');

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);

    try {
      const backendResp = await fetch(
        `${BACKEND_API_URL}/api/v1/contents/${id}/reader/translate`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authHeader ? { Authorization: authHeader } : {}),
          },
          signal: controller.signal,
        },
      );

      const body = await backendResp.text();
      return new NextResponse(body, {
        status: backendResp.status,
        headers: {
          'Content-Type': backendResp.headers.get('content-type') || 'application/json',
        },
      });
    } finally {
      clearTimeout(timer);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Translation proxy failed';
    return NextResponse.json(
      { detail: `翻译代理失败: ${message}` },
      { status: 504 },
    );
  }
}
