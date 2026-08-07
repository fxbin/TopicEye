/**
 * API client 核心基础设施（从 lib/api.ts 抽出）。
 *
 * 安全设计：
 * - Auth token 存储在 HttpOnly cookie 中，JS 无法读取，防 XSS 窃取。
 * - 所有 fetch 请求通过 credentials: 'include' 自动携带 cookie。
 * - getAuthToken() 仅检查非 HttpOnly 的存在标记 cookie，返回 "1" 或 null。
 * - getAuthTokenExpiresAt() 从非 HttpOnly cookie 读取过期时间。
 *
 * 包含：
 * - BASE_URL / FAVORITE_STATE_BATCH_SIZE 常量
 * - formatApiErrorDetail    错误详情格式化
 * - getAuthToken/setAuthToken  登录状态存取（cookie，非真实 token）
 * - getAuthTokenExpiresAt/setAuthTokenExpiresAt  token 过期时间存取
 * - request<T>              通用 fetch 封装（鉴权 cookie + 401 自动 refresh + 错误处理 + JSON 解析）
 * - assertUniqueIds         ID 去重校验
 * - chunkArray              数组分块
 *
 * 所有业务域 API 对象（authApi / sourcesApi / contentsApi 等）通过
 * `import { request } from './_core'` 共用本模块。
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';
export { BASE_URL };

export const FAVORITE_STATE_BATCH_SIZE = 200;

// Cookie 名称（与后端 config.py 保持一致）
const AUTH_PRESENCE_COOKIE = 'topiceye_auth_present';
const AUTH_EXPIRES_COOKIE = 'topiceye_auth_expires_at';

function formatDetailItem(item: unknown): string | undefined {
  if (!item) return undefined;
  if (typeof item === 'string') return item;
  if (typeof item !== 'object') return String(item);

  const record = item as Record<string, unknown>;
  // 空对象不序列化为 "{}"，交给上层 fallback 到其他字段
  if (Object.keys(record).length === 0) return undefined;

  const message = record.msg || record.message || record.detail;
  const loc = Array.isArray(record.loc) ? record.loc.join('.') : undefined;

  if (typeof message === 'string' && loc) {
    return `${loc}: ${message}`;
  }
  if (typeof message === 'string') {
    return message;
  }

  try {
    return JSON.stringify(record);
  } catch {
    return undefined;
  }
}

export function formatApiErrorDetail(detail: unknown): string | undefined {
  if (!detail) return undefined;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map(formatDetailItem)
      .filter((item): item is string => Boolean(item));
    return parts.length ? parts.join('；') : undefined;
  }
  return formatDetailItem(detail);
}

export function assertUniqueIds(ids: number[], message: string): void {
  if (ids.length !== new Set(ids).size) {
    throw new Error(message);
  }
}

export function chunkArray<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

// ── Cookie 读写工具 ──────────────────────────────────────────────────

function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function setCookie(name: string, value: string, maxAgeDays: number): void {
  if (typeof document === 'undefined') return;
  const maxAge = maxAgeDays * 86400;
  document.cookie = `${name}=${encodeURIComponent(value)}; max-age=${maxAge}; path=/; SameSite=Lax`;
}

function deleteCookie(name: string): void {
  if (typeof document === 'undefined') return;
  document.cookie = `${name}=; max-age=0; path=/; SameSite=Lax`;
}

// ── 登录状态管理（基于 cookie，不存储真实 token） ────────────────────
//
// 真实 token 在 HttpOnly cookie 中，JS 无法读取。
// AUTH_PRESENCE_COOKIE 是一个非 HttpOnly 的标记 cookie，值为 "1"。
// getAuthToken() 返回该标记值或 null，用于判断是否已登录。
// setAuthToken() 设置或清除该标记。
// setAuthToken('any-truthy-string') → 标记为已登录
// setAuthToken(null) → 标记为已登出

export function getAuthToken(): string | null {
  return getCookie(AUTH_PRESENCE_COOKIE);
}

export function setAuthToken(token: string | null): void {
  if (token) {
    setCookie(AUTH_PRESENCE_COOKIE, '1', 30);
  } else {
    deleteCookie(AUTH_PRESENCE_COOKIE);
    deleteCookie(AUTH_EXPIRES_COOKIE);
  }
}

export function getAuthTokenExpiresAt(): string | null {
  return getCookie(AUTH_EXPIRES_COOKIE);
}

export function setAuthTokenExpiresAt(expiresAt: string | null): void {
  if (expiresAt) {
    setCookie(AUTH_EXPIRES_COOKIE, expiresAt, 30);
  } else {
    deleteCookie(AUTH_EXPIRES_COOKIE);
  }
}

// ── Token refresh 机制 ──────────────────────────────────────────────
//
// 当 request<T>() 收到 401 时，自动调用 POST /auth/refresh 尝试续期。
// 续期成功 → 重试原请求；续期失败 → 抛出原始 401 错误（触发上层登出）。
//
// 并发保护：多个请求同时 401 时，只发一个 refresh，其余等同一个 Promise。
// _refreshPromise !== null 表示 refresh 正在进行中。

let _refreshPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  // 已有 refresh 在进行中，复用同一个 Promise
  if (_refreshPromise) return _refreshPromise;

  // 检查是否存在登录标记 cookie
  if (!getAuthToken()) return false;

  _refreshPromise = (async () => {
    try {
      const url = `${BASE_URL}/auth/refresh`;
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) return false;

      const data = await response.json() as {
        access_token: string;
        expires_at: string;
        user: unknown;
      };

      // 后端已通过 Set-Cookie 更新了 HttpOnly cookie，
      // 前端只需更新 expires_at 辅助 cookie
      setAuthTokenExpiresAt(data.expires_at);
      return true;
    } catch {
      return false;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}

/** Generic fetch wrapper with error handling + auto token refresh on 401 */
export async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;
  const config: RequestInit = {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  };

  let response: Response;
  try {
    response = await fetch(url, config);
  } catch (err) {
    // 网络层失败（后端不可达/重启中）：抛出带标记的错误，调用方可据此保留登录态
    const networkErr = new Error(
      err instanceof Error ? err.message : 'Network request failed'
    ) as Error & { isNetworkError?: boolean };
    networkErr.isNetworkError = true;
    throw networkErr;
  }

  // 401 自动 refresh：尝试续期后重试原请求（仅限非 refresh 端点自身）
  if (response.status === 401 && !endpoint.includes('/auth/refresh')) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      // 重试原请求（cookie 已更新，credentials: 'include' 自动携带）
      const retryConfig: RequestInit = {
        ...options,
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
        },
      };
      try {
        response = await fetch(url, retryConfig);
      } catch (err) {
        const networkErr = new Error(
          err instanceof Error ? err.message : 'Network request failed'
        ) as Error & { isNetworkError?: boolean };
        networkErr.isNetworkError = true;
        throw networkErr;
      }
    }
  }

  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    let error: { detail?: unknown; message?: string; error?: string } = { message: response.statusText };
    if (errorText) {
      try {
        error = JSON.parse(errorText);
      } catch {
        error = { message: errorText };
      }
    }
    const detail = formatApiErrorDetail(error.detail);
    // 后端可能用 message 或 error 字段返回错误描述
    const message = typeof error.message === 'string' ? error.message : undefined;
    const errorField = typeof error.error === 'string' ? error.error : undefined;
    const apiErr = new Error(detail || message || errorField || `API Error: ${response.status}`) as Error & {
      status?: number;
      isAuthError?: boolean;
    };
    apiErr.status = response.status;
    // 401/403 = token 无效或过期，调用方应清登录态；其他状态码（500/502/503）不应登出
    apiErr.isAuthError = response.status === 401 || response.status === 403;
    throw apiErr;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text) {
    return undefined as T;
  }

  return JSON.parse(text) as T;
}
