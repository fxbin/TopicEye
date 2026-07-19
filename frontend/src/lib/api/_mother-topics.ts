/**
 * _mother-topics API objects extracted from lib/api.ts.
 * Uses request from ./_core.
 */

import { request } from './_core';
import type { ContentScoringResult, MotherTopic, MotherTopicMutation } from '@/types/trending';
import type { FanqieBook, FanqieCategory, QimaoBook, WebnovelWeeklyReport, ZhihuAlbum, ZhihuCategory } from '@/types/webnovel';

// ─── Mother Topics API ──────────────────────────────────────────────

export const motherTopicsApi = {
  /** 列出所有母题 */
  list(active_only = false): Promise<MotherTopic[]> {
    return request(`/mother-topics?active_only=${active_only}`);
  },

  /** 创建母题 */
  create(data: {
    name: string;
    description?: string;
    keywords: string[];
    weight?: number;
    content_type?: string;
    target_reader?: string;
    is_active?: boolean;
    display_order?: number;
  }): Promise<MotherTopic> {
    return request('/mother-topics', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 更新母题 */
  update(
    id: number,
    data: MotherTopicMutation
  ): Promise<MotherTopic> {
    return request(`/mother-topics/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /** 删除母题（软删除） */
  delete(id: number): Promise<{ ok: boolean; message: string }> {
    return request(`/mother-topics/${id}`, { method: 'DELETE' });
  },

  /** Fork 系统模板到当前用户名下（幂等，首次访问 /my-topics 时懒触发） */
  forkDefaults(): Promise<{ forked: number; skipped: number; message: string }> {
    return request('/mother-topics/fork-defaults', { method: 'POST' });
  },

  /** 对内容按母题打分 */
  score(data: {
    title: string;
    summary?: string;
    source?: string;
    hot_value?: number;
  }): Promise<ContentScoringResult> {
    return request('/mother-topics/score', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 批量对多条内容按母题打分（只查一次 DB） */
  scoreBatch(items: Array<{
    title: string;
    summary?: string;
    hot_value?: number;
  }>): Promise<{ results: ContentScoringResult[] }> {
    return request('/mother-topics/score-batch', {
      method: 'POST',
      body: JSON.stringify({ items }),
    });
  },

  /** 对已入库内容重新匹配母题 */
  matchContent(contentId: number): Promise<{
    content_id: number;
    title: string;
    top_topic: string | null;
    top_score: number;
    all_scores: Array<{ name: string; keyword_score: number; weight: number; final: number }>;
  }> {
    return request(`/mother-topics/match/${contentId}`);
  },
};

/* ── 番茄小说 ── */

export const fanqieApi = {
  /** 获取全部分类 */
  categories(): Promise<FanqieCategory[]> {
    return request('/fanqie/categories');
  },

  /** 获取四大榜单（或指定类型） */
  rankings(type?: string): Promise<Record<string, {
    label: string;
    count: number;
    books: FanqieBook[];
  }>> {
    const params = type ? `?type=${type}` : '';
    return request(`/fanqie/rankings${params}`);
  },

  /** 获取分类下图书 */
  categoryBooks(
    fanqieId: string,
    params?: { rank_type?: string; limit?: number },
  ): Promise<{ fanqie_id: string; count: number; books: FanqieBook[] }> {
    const qs = new URLSearchParams();
    if (params?.rank_type) qs.set('rank_type', params.rank_type);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString();
    return request(`/fanqie/category/${fanqieId}/books${query ? '?' + query : ''}`);
  },

  /** 手动触发全量同步 */
  sync(): Promise<{ categories: number; elapsed_seconds: number }> {
    return request('/fanqie/sync', { method: 'POST' });
  },
};

export const webnovelReportsApi = {
  weekly(days = 7): Promise<WebnovelWeeklyReport> {
    return request(`/webnovel/reports/weekly?days=${days}`);
  },
};


// ─── 七猫小说 API ────────────────────────────────────────────────────────────

export const qimaoApi = {
  list(channel: string, rankType: string, limit = 20, offset = 0): Promise<{
    channel: string; rank_type: string; count: number;
    books: QimaoBook[];
  }> {
    const qs = new URLSearchParams({ channel, rank_type: rankType, limit: String(limit), offset: String(offset) });
    return request(`/qimao/books?${qs}`);
  },
  sync(): Promise<{ books: number; elapsed_seconds: number }> {
    return request('/qimao/sync', { method: 'POST' });
  },
};

// ─── 知乎盐选 API ────────────────────────────────────────────────────────────

export const zhihuApi = {
  list(sortType = 'hottest', category?: string, subcategory?: string, limit = 20, offset = 0): Promise<{
    sort_type: string; category: string; count: number; total: number;
    albums: ZhihuAlbum[];
  }> {
    const qs = new URLSearchParams({ sort_type: sortType, limit: String(limit), offset: String(offset) });
    if (category) qs.set('category', category);
    if (subcategory) qs.set('subcategory', subcategory);
    return request(`/zhihu/albums?${qs}`);
  },
  categories(parentId?: string): Promise<{ count: number; categories: ZhihuCategory[] }> {
    const qs = parentId ? `?parent_id=${parentId}` : '';
    return request(`/zhihu/categories${qs}`);
  },
  sync(): Promise<{ status: string; message: string }> {
    return request('/zhihu/sync', { method: 'POST' });
  },
};
