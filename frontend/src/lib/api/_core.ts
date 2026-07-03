/**
 * API client 核心基础设施（从 lib/api.ts 抽出）。
 *
 * 包含：
 * - BASE_URL / AUTH_TOKEN_STORAGE_KEY / FAVORITE_STATE_BATCH_SIZE 常量
 * - formatApiErrorDetail    错误详情格式化
 * - getAuthToken/setAuthToken  token 存取
 * - request<T>              通用 fetch 封装（鉴权 + 错误处理 + JSON 解析）
 * - assertUniqueIds         ID 去重校验
 * - chunkArray              数组分块
 *
 * 所有业务域 API 对象（authApi / sourcesApi / contentsApi 等）通过
 * `import { request } from './_core'` 共用本模块。
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';
export { BASE_URL };

export const AUTH_TOKEN_STORAGE_KEY = 'topiceye_auth_token';
export const FAVORITE_STATE_BATCH_SIZE = 200;

function formatDetailItem(item: unknown): string | undefined {
  if (!item) return undefined;
  if (typeof item === 'string') return item;
  if (typeof item !== 'object') return String(item);

  const record = item as Record<string, unknown>;
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

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (token) {
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    }
  } catch {}
}

/** Generic fetch wrapper with error handling */
export async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;
  const token = getAuthToken();
  const config: RequestInit = {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    let error: { detail?: unknown; message?: string } = { message: response.statusText };
    if (errorText) {
      try {
        error = JSON.parse(errorText);
      } catch {
        error = { message: errorText };
      }
    }
    const detail = formatApiErrorDetail(error.detail);
    const message = typeof error.message === 'string' ? error.message : undefined;
    throw new Error(detail || message || `API Error: ${response.status}`);
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