/**
 * Contents API — 内容管理、分类、低粉爆文。
 *
 * 从 _domains.ts 拆出。
 */

import { request } from './_core';
import type { ContentCategoryItem, ScoringFlowResponse } from '@/types/contents';
import type { ArticleReaderSnapshot, ContentItem, ContentRelation, EvidenceMark, EvidenceLink, PaginatedResponse, TopicInfo, ContentFilterParams } from '@/types';
import { BASE_URL } from './_core';

export const contentsApi = {
  /** 获取内容列表 */
  list(params?: ContentFilterParams): Promise<PaginatedResponse<ContentItem>> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/contents${query}`);
  },

  /** 获取单条内容 */
  get(id: number): Promise<ContentItem> {
    return request(`/contents/${id}`);
  },

  /** 获取或按需生成安全的站内阅读快照。 */
  reader(id: number, refresh = false): Promise<ArticleReaderSnapshot> {
    return request(`/contents/${id}/reader${refresh ? '?refresh=true' : ''}`, { method: 'POST' });
  },

  /** 翻译站内阅读正文为中文（已有缓存直接返回） */
  translateReader(id: number): Promise<ArticleReaderSnapshot> {
    return request(`/contents/${id}/reader/translate`, { method: 'POST' });
  },

  /** 切换收藏状态 */
  toggleFavorite(id: number): Promise<{ is_favorited: boolean; favorite_id?: number | null }> {
    return request(`/contents/${id}/favorite`, { method: 'POST' });
  },

  /** 获取内容的关联内容列表 */
  getRelations(id: number, limit = 20): Promise<{ content_id: number; relations: ContentRelation[]; count: number }> {
    return request(`/contents/${id}/relations?limit=${limit}`);
  },

  /** 获取收藏列表 */
  listFavorites(params?: { page?: number; page_size?: number }): Promise<PaginatedResponse<ContentItem>> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/contents/favorites/list${query}`);
  },

  /** 当日精选（自动 Top 30%） */
  todayPicks(params?: { category?: string; content_type?: string; time_range?: string; limit?: number }): Promise<{
    items: ContentItem[];
    topics: TopicInfo[];
    total: number;
    event_members_hidden: number;
  }> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== '')
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/contents/today-picks${query}`);
  },

  /** 获取跨源证据 */
  getEvidence(id: number): Promise<{ content_id: number; evidence_mark: EvidenceMark | null; evidence_links: EvidenceLink[] }> {
    return request(`/contents/${id}/evidence`);
  },

  /** 批量获取证据标记（避免 N+1） */
  getEvidenceBatch(ids: number[]): Promise<{ marks: Record<string, EvidenceMark> }> {
    return request(`/contents/evidence-batch?ids=${ids.join(',')}`);
  },

  /** 当日计数（今日选题 + 当日精选的 badge 数字） */
  todayCount(): Promise<{ today_content: number; today_picks: number }> {
    return request('/contents/today-count');
  },

  scoringFlow(params?: { hours?: number; limit?: number }): Promise<ScoringFlowResponse> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/contents/scoring-flow${query}`);
  },

  /** 忽略/不感兴趣 */
  ignore(id: number, reason: string = 'not_interested'): Promise<{ content_id: number; ignored: boolean; reason: string }> {
    return request(`/contents/${id}/ignore?reason=${encodeURIComponent(reason)}`, { method: 'POST' });
  },

  /** 取消忽略 */
  unignore(id: number): Promise<{ content_id: number; ignored: boolean; removed: boolean }> {
    return request(`/contents/${id}/ignore`, { method: 'DELETE' });
  },

  /** 记录证据内容交互（fire-and-forget，不抛错） */
  trackEvidenceInteraction(
    contentId: number,
    interactionType: 'click' | 'favorite' | 'unfavorite' | 'adopt' | 'feedback_positive' | 'feedback_negative',
  ): void {
    const url = `${BASE_URL}/contents/${contentId}/evidence-interaction?interaction_type=${interactionType}`;
    fetch(url, { method: 'POST', credentials: 'include' }).catch(() => {});
  },
};

export const contentCategoriesApi = {
  list(): Promise<{ categories: ContentCategoryItem[] }> {
    return request('/categories');
  },
};

// ─── Viral (低粉爆文) API ───

export const viralApi = {
  /** 获取低粉爆文列表 */
  async list(params?: {
    category?: string;
    hours?: number;
    sort_by?: string;
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<ContentItem> & { total?: number }> {
    const page = params?.page || 1;
    const pageSize = params?.page_size || 20;
    const query = '?' + new URLSearchParams(
      Object.entries({
        page: String(page),
        page_size: String(pageSize),
        sort_by: 'low_follower_viral',
        hours: params?.hours !== undefined ? String(params.hours) : '',
        category: params?.category || '',
      }).filter(([, v]) => v !== '') as [string, string][]
    ).toString();
    return request(`/contents${query}`);
  },
};
