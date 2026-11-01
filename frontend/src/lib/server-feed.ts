/**
 * 首屏 feed 的服务端直出。
 *
 * 背景：首页原本整页是 'use client'，内容列表在 useEffect 里才拉——
 * 首屏最大文本块（第一张选题卡的标题）必须等「JS bundle → hydration →
 * 客户端取数 → 渲染」整条链路走完才画得出来，LCP 被客户端链路拖着。
 *
 * 这里在服务端把首屏要用的三份数据一次取好，直接进首屏 HTML：
 * - 内容列表（第一页，含 feed_snapshot，供「加载更多」继续用同一快照）
 * - 分类（chips 行）
 * - 标签分面（chips 行；不一起直出的话，内容画出来之后标签行再撑开一次，
 *   那是净新增的 CLS）
 *
 * 与客户端口径必须一致，所以查询参数与客户端的默认值对齐，
 * 分类合并走共用的纯函数（lib/content-categories.ts）。
 *
 * 取数失败不阻断渲染：超时或后端不可达时返回 ok=false，客户端照旧自己取。
 */

import { cookies } from 'next/headers';
import type { ContentItem } from '@/types';
import { mergeCategoryOptions } from './content-categories';
import {
  FEED_PAGE_SIZE,
  INITIAL_HOURS,
  buildFeedQuery,
  buildTagFacetQuery,
} from './feed-query';

// Server Component 里不能走 Next 的 rewrite 代理，要直接访问后端
const BACKEND_URL = process.env.BACKEND_API_URL || 'http://127.0.0.1:8102';
const API_BASE = `${BACKEND_URL}/api/v1`;

const FETCH_TIMEOUT_MS = 3000;

export interface InitialTagFacet {
  tag: string;
  count: number;
}

export interface InitialFeed {
  /** 首屏内容（第一页） */
  items: ContentItem[];
  /** 内容总数（用于「加载更多」提示） */
  total: number;
  /** 浏览快照；「加载更多」必须带它，否则后端返回 409 */
  feedSnapshot: string | null;
  /** 分类 chips */
  categories: string[];
  /** 标签分面 chips */
  tagFacets: InitialTagFacet[];
  /** 取数时的用户 id（用于客户端判断"用户变了要重新取"） */
  userId: number | null;
  /** 服务端取数是否成功；false 表示客户端要自己再取一遍 */
  ok: boolean;
}

export interface InitialFeedOptions {
  /** 覆盖首屏参数（测试用） */
  limit?: number;
  hours?: number;
  /** 取数时的用户 id；客户端用它判断"用户变了要重新取" */
  userId?: number | null;
}

async function fetchJson<T>(path: string, cookieHeader: string): Promise<T | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: cookieHeader ? { Cookie: cookieHeader } : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });
    if (!response.ok) return null;
    const text = await response.text();
    if (!text) return null;
    return JSON.parse(text) as T;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

interface ContentsResponse {
  items?: ContentItem[];
  total?: number;
  feed_snapshot?: string;
}

interface CategoriesResponse {
  categories?: Array<{ name?: string }>;
}

interface TagFacetsResponse {
  tags?: InitialTagFacet[];
}

export async function fetchInitialFeed(options: InitialFeedOptions = {}): Promise<InitialFeed> {
  const limit = options.limit ?? FEED_PAGE_SIZE;
  const hours = options.hours ?? INITIAL_HOURS;

  const cookieStore = await cookies();
  const token = cookieStore.get('topiceye_auth')?.value;
  const cookieHeader = token ? `topiceye_auth=${token}` : '';

  const [contents, categories, tagFacets] = await Promise.all([
    fetchJson<ContentsResponse>(`/contents?${buildFeedQuery(limit, hours)}`, cookieHeader),
    fetchJson<CategoriesResponse>('/categories', cookieHeader),
    fetchJson<TagFacetsResponse>(`/contents/tag-facets?${buildTagFacetQuery(hours)}`, cookieHeader),
  ]);

  if (!contents || !contents.items) {
    // 任一关键数据缺失 → 交给客户端自己取，行为与改造前一致
    return {
      items: [],
      total: 0,
      feedSnapshot: null,
      categories: ['全部'],
      tagFacets: [],
      userId: null,
      ok: false,
    };
  }

  const items = contents.items;
  const categoryNames = (categories?.categories || [])
    .map((category) => category.name || '')
    .filter(Boolean);

  return {
    items,
    total: contents.total ?? items.length,
    feedSnapshot: contents.feed_snapshot ?? null,
    categories: mergeCategoryOptions(['全部'], categoryNames, items),
    tagFacets: tagFacets?.tags || [],
    userId: options.userId ?? null,
    ok: true,
  };
}
