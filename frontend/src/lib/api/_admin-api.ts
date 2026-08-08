/**
 * Admin & User API — 收藏、选题、分析、Token、证据、内容事件。
 *
 * 从 _domains.ts 拆出。
 */

import { request } from './_core';
import type { ContentAnalysis, PaginatedResponse, TopicInfo, TopicFilterParams, FavoriteItem, FavoriteStatus, FavoriteTargetType } from '@/types';
import type { FavoriteCreatePayload, FavoriteTargetState } from '@/lib/favorites';
import { assertUniqueIds, chunkArray, FAVORITE_STATE_BATCH_SIZE } from './_core';
import type { TopicGroupResponse } from '@/types/contents';

// ─── Favorites API ───

export const favoritesApi = {
  list(params?: {
    page?: number;
    page_size?: number;
    target_type?: FavoriteTargetType | '';
    status?: FavoriteStatus | '';
    keyword?: string;
  }): Promise<PaginatedResponse<FavoriteItem>> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== '')
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/favorites${query}`);
  },

  /** Lightweight index — only id/target_type/target_key/target_id, no pagination. */
  index(): Promise<{ items: Array<{ id: number; target_type: string; target_key: string; target_id: number | null }>; total: number }> {
    return request('/favorites/index');
  },

  create(data: FavoriteCreatePayload): Promise<FavoriteItem> {
    return request('/favorites', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async state(params: {
    target_type: FavoriteTargetType;
    target_ids?: number[];
    target_keys?: string[];
  }): Promise<{ items: FavoriteTargetState[] }> {
    const targetIds = params.target_ids || [];
    const targetKeys = params.target_keys || [];
    if (targetIds.length + targetKeys.length > FAVORITE_STATE_BATCH_SIZE) {
      const responses = await Promise.all([
        ...chunkArray(targetIds, FAVORITE_STATE_BATCH_SIZE).map((ids) => (
          favoritesApi.state({ target_type: params.target_type, target_ids: ids })
        )),
        ...chunkArray(targetKeys, FAVORITE_STATE_BATCH_SIZE).map((keys) => (
          favoritesApi.state({ target_type: params.target_type, target_keys: keys })
        )),
      ]);
      return { items: responses.flatMap((response) => response.items || []) };
    }

    const qs = new URLSearchParams();
    qs.set('target_type', params.target_type);
    if (targetIds.length) qs.set('target_ids', targetIds.join(','));
    if (targetKeys.length) qs.set('target_keys', targetKeys.join(','));
    return request(`/favorites/state?${qs.toString()}`);
  },

  update(id: number, data: { status?: FavoriteStatus; note?: string | null; tags?: unknown; snapshot?: Record<string, unknown> | null }): Promise<FavoriteItem> {
    return request(`/favorites/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  reorder(status: FavoriteStatus, orderedIds: number[]): Promise<FavoriteItem[]> {
    assertUniqueIds(orderedIds, '收藏排序包含重复项，请刷新后重试');
    return request('/favorites/reorder', {
      method: 'POST',
      body: JSON.stringify({ status, ordered_ids: orderedIds }),
    });
  },

  reorderBoard(columns: Array<{ status: FavoriteStatus; orderedIds: number[] }>): Promise<FavoriteItem[]> {
    const seen = new Set<number>();
    for (const column of columns) {
      assertUniqueIds(column.orderedIds, '收藏排序包含重复项，请刷新后重试');
      for (const id of column.orderedIds) {
        if (seen.has(id)) {
          throw new Error('收藏排序包含跨列重复项，请刷新后重试');
        }
        seen.add(id);
      }
    }
    return request('/favorites/reorder-board', {
      method: 'POST',
      body: JSON.stringify({
        columns: columns.map((column) => ({
          status: column.status,
          ordered_ids: column.orderedIds,
        })),
      }),
    });
  },

  bulkStatus(status: FavoriteStatus, ids: number[]): Promise<FavoriteItem[]> {
    assertUniqueIds(ids, '批量移动包含重复收藏，请刷新后重试');
    return request('/favorites/bulk-status', {
      method: 'POST',
      body: JSON.stringify({ status, ids }),
    });
  },

  bulkDelete(ids: number[]): Promise<{ deleted: number }> {
    assertUniqueIds(ids, '批量删除包含重复收藏，请刷新后重试');
    return request('/favorites/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },

  delete(id: number): Promise<{ deleted: boolean }> {
    return request(`/favorites/${id}`, { method: 'DELETE' });
  },
};

// ─── Topics API ───

export const topicsApi = {
  /** 获取选题分组列表 */
  list(params?: TopicFilterParams): Promise<{items: TopicGroupResponse[]; total: number}> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== '')
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/topics${query}`);
  },

  /** 获取选题详情（含成员内容） */
  get(id: number): Promise<{topic: TopicGroupResponse; items: Array<{id: number; title: string; url: string; source_name: string}>}> {
    return request(`/topics/${id}`);
  },

  /** 触发聚类 */
  cluster(): Promise<{status: string; stats: Record<string, unknown>}> {
    return request('/topics/cluster', { method: 'POST' });
  },
};

// ─── Analyses API ───

export const analysesApi = {
  /** 分析单条内容 */
  analyzeContent(id: number): Promise<ContentAnalysis> {
    return request(`/analyses/content/${id}`, { method: 'POST' });
  },

  /** 获取内容的分析结果 */
  getAnalysis(contentId: number): Promise<ContentAnalysis> {
    return request(`/analyses/content/${contentId}`);
  },

  /** 批量分析 */
  analyzeBatch(contentIds: number[]): Promise<ContentAnalysis[]> {
    return request('/analyses/batch', {
      method: 'POST',
      body: JSON.stringify(contentIds),
    });
  },

  /** 分析所有待处理内容 */
  analyzePending(params?: { limit?: number; hours?: number; sync?: boolean }): Promise<{
    message: string;
    count: number;
    ids?: number[];
    queued_ids?: number[];
    skipped_inflight_ids?: number[];
    analyzed_ids?: number[];
    job_id?: string | null;
    hours?: number | null;
    mode?: 'background' | 'sync';
  }> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '?limit=20';
    return request(`/analyses/pending${query}`, { method: 'POST' });
  },

  /** 查询后台分析任务状态 */
  getJob(jobId: string): Promise<{
    job_id: string;
    status: 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'SKIPPED' | 'EXPIRED' | string;
    content_ids: number[];
    queued_ids: number[];
    skipped_inflight_ids: number[];
    analyzed_ids: number[];
    failed_ids: number[];
    pending_ids: number[];
    count: number;
    queued_count: number;
    skipped_inflight_count: number;
    analyzed_count: number;
    failed_count: number;
    queued_at: string;
    started_at?: string | null;
    finished_at?: string | null;
    error_message?: string | null;
  }> {
    return request(`/analyses/jobs/${jobId}`);
  },

  /** 获取分析列表 */
  list(params?: { page?: number; page_size?: number; min_creator_score?: number }): Promise<PaginatedResponse<ContentAnalysis>> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/analyses${query}`);
  },
};

// ─── API Tokens (个人 API token，供外部 agent / 脚本调用) ───

export interface ApiTokenItem {
  id: number;
  name: string;
  token_prefix: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string | null;
}

export const apiTokensApi = {
  /** 列出当前用户的所有 API token */
  list(): Promise<{ count: number; tokens: ApiTokenItem[] }> {
    return request('/me/api-tokens');
  },

  /** 创建 API token（明文 token 仅在响应中返回一次） */
  create(data: { name: string; expires_at?: string }): Promise<{ token: string; record: ApiTokenItem }> {
    return request('/me/api-tokens', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 撤销 API token */
  revoke(id: number): Promise<{ success: boolean }> {
    return request(`/me/api-tokens/${id}/revoke`, { method: 'POST' });
  },

  /** 删除 API token */
  remove(id: number): Promise<void> {
    return request(`/me/api-tokens/${id}`, { method: 'DELETE' });
  },
};

// ─── Evidence (可信线索) Admin API ───

export interface EvidenceStats {
  marks: {
    total: number;
    by_level: Record<string, number>;
    has_primary_source: number;
    has_official_source: number;
  };
  links: {
    total: number;
    by_type: Record<string, number>;
  };
  profiles: {
    total_system_sources: number;
    profiled_sources: number;
    unprofiled_sources: number;
    by_kind: Record<string, number>;
  };
}

export interface EvidenceEffectStats {
  window_days: number;
  marked: {
    total_content: number;
    interactions_by_type: Record<string, number>;
    total_interactions: number;
    interaction_rate: number;
  };
  unmarked: {
    total_content: number;
    interactions_by_type: Record<string, number>;
    total_interactions: number;
    interaction_rate: number;
  };
  comparison: Record<string, number | null>;
}

export const evidenceApi = {
  /** 获取证据聚合统计 */
  getStats(): Promise<EvidenceStats> {
    return request('/admin/evidence/stats');
  },

  /** 获取证据效果统计（交互率对比） */
  getEffectStats(days?: number): Promise<EvidenceEffectStats> {
    const query = days ? `?days=${days}` : '';
    return request(`/admin/evidence/effect-stats${query}`);
  },

  /** 手动触发跨源证据发现 */
  discover(hours?: number): Promise<{ triggered: boolean; stats: Record<string, number> }> {
    const query = hours ? `?hours=${hours}` : '';
    return request(`/admin/evidence/discover${query}`, { method: 'POST' });
  },
};

// ─── Content Events (内容事件归一化) Admin API ───

export type ContentEventRelation = 'duplicate' | 'corroboration' | 'update';
export type ContentEventReviewStatus = 'pending' | 'auto' | 'confirmed' | 'rejected';
export type ContentEventNormalizationMode = 'shadow' | 'write';
export type ContentEventNormalizationScope = 'public' | 'user';

export interface ContentEventReviewItem {
  id: number;
  event_id: number;
  event_version: number;
  content_id: number;
  title: string;
  source_name: string | null;
  source_type: string | null;
  relation_type: ContentEventRelation;
  confidence: number;
  match_method: string | null;
  detector_version: string | null;
  reason: string | null;
  review_status: ContentEventReviewStatus;
  matched_at: string;
  updated_at: string | null;
}

export interface ContentEventReviewListResponse {
  items: ContentEventReviewItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ContentEventMutationResponse {
  event_id: number;
  version: number;
  canonical_content_id: number;
  canonical_locked: boolean;
}

export interface ContentEventNormalizeRequest {
  hours: number;
  mode: ContentEventNormalizationMode;
  scope: ContentEventNormalizationScope;
  owner_user_id?: number;
}

export interface ContentEventNormalizeResponse {
  accepted: boolean;
  idempotency_key: string;
  mode: ContentEventNormalizationMode;
  scope: ContentEventNormalizationScope;
  owner_user_id: number | null;
  result: Record<string, unknown>;
}

export const contentEventsAdminApi = {
  /** 服务端分页读取指定审核状态的事件成员。 */
  listReviews(params: {
    page: number;
    page_size: number;
    review_status: ContentEventReviewStatus;
  }): Promise<ContentEventReviewListResponse> {
    const query = new URLSearchParams({
      page: String(params.page),
      page_size: String(params.page_size),
      review_status: params.review_status,
    });
    return request(`/admin/content-events/reviews?${query.toString()}`);
  },

  /** 接受或拒绝一条事件成员关系；expected_version 用于 OCC。 */
  reviewMember(
    memberId: number,
    data: {
      decision: 'accept' | 'reject';
      relation_type?: ContentEventRelation;
      reason: string;
      expected_version: number;
    },
  ): Promise<ContentEventMutationResponse> {
    return request(`/admin/content-events/members/${memberId}/review`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  /** 发起一次带幂等键的近期内容归一化。 */
  normalize(
    data: ContentEventNormalizeRequest,
    idempotencyKey: string,
  ): Promise<ContentEventNormalizeResponse> {
    return request('/admin/content-events/normalize', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(data),
    });
  },
};
