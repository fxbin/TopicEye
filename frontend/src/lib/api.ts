/**
 * TopicEye API Client
 * Backend API wrapper using fetch
 */

import type {
  Source,
  CreateSourceRequest,
  UpdateSourceRequest,
  ContentItem,
  ContentAnalysis,
  TopicFilterParams,
  ContentFilterParams,
  PaginatedResponse,
  SyncResult,
  TopicInfo,
  FavoriteItem,
  FavoriteStatus,
  FavoriteTargetType,
  MonthlyDigest,
  MonthlyDigestListResponse,
  MonthlyDigestMonthsResponse,
  WeeklyDigest,
  WeeklyDigestListResponse,
  WeeklyDigestWeeksResponse,
  AuthTokenResponse,
  AuthUser,
  IntegrationStatus,
  PlanCatalogResponse,
  WeReadSyncResult,
  NotificationListResponse,
} from '@/types';
import type { FavoriteCreatePayload, FavoriteTargetState } from '@/lib/favorites';
import type {
  RSSHubInstance,
  StatsOverview,
  StatsSourceItem,
  StatsCategoryItem,
  StatsTrendItem,
  StatsNovelPlatform,
  StatsDashboard,
  JobStatsByStatus,
  JobStatsByJobKey,
  JobStatsRecentFailure,
  JobStatsResponse,
} from '@/types/stats';

export type { ContentItem, CreateSourceRequest, UpdateSourceRequest };
export type FeedbackType = 'like' | 'dislike' | 'skip' | 'not_relevant' | 'outdated' | 'great_pick';
// 统计类型 re-export 保持向后兼容（外部通过 @/lib/api 导入）
export type {
  RSSHubInstance,
  StatsOverview,
  StatsSourceItem,
  StatsCategoryItem,
  StatsTrendItem,
  StatsNovelPlatform,
  StatsDashboard,
  JobStatsByStatus,
  JobStatsByJobKey,
  JobStatsRecentFailure,
  JobStatsResponse,
};

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';
const AUTH_TOKEN_STORAGE_KEY = 'topiceye_auth_token';
const FAVORITE_STATE_BATCH_SIZE = 200;

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

function assertUniqueIds(ids: number[], message: string): void {
  if (ids.length !== new Set(ids).size) {
    throw new Error(message);
  }
}

function chunkArray<T>(items: T[], size: number): T[][] {
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
async function request<T>(
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

// ─── Auth API ───

export const authApi = {
  register(data: { email: string; password: string; display_name?: string | null }): Promise<AuthTokenResponse> {
    return request('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  login(data: { email: string; password: string }): Promise<AuthTokenResponse> {
    return request('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  me(): Promise<AuthUser> {
    return request('/auth/me');
  },

  logout(): Promise<{ logged_out: boolean }> {
    return request('/auth/logout', { method: 'POST' });
  },
};

// ─── Plans API ───

export const plansApi = {
  list(): Promise<PlanCatalogResponse> {
    return request('/plans');
  },
};

// ─── Notifications API ───

export const notificationsApi = {
  unreadCount(): Promise<{ count: number }> {
    return request('/notifications/unread-count');
  },

  list(params?: { unread?: boolean; limit?: number; offset?: number }): Promise<NotificationListResponse> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/notifications${query}`);
  },

  markRead(id: number): Promise<{ success: boolean }> {
    return request(`/notifications/${id}/read`, { method: 'POST' });
  },

  markAllRead(): Promise<{ marked: number }> {
    return request('/notifications/read-all', { method: 'POST' });
  },

  delete(id: number): Promise<{ success: boolean }> {
    return request(`/notifications/${id}`, { method: 'DELETE' });
  },
};

// ─── Integrations API ───

export const integrationsApi = {
  getWeRead(): Promise<IntegrationStatus> {
    return request('/integrations/weread');
  },

  updateWeRead(data: { api_key: string; config?: Record<string, unknown> }): Promise<IntegrationStatus> {
    return request('/integrations/weread', {
      method: 'PUT',
      body: JSON.stringify({ api_key: data.api_key, config: data.config || {} }),
    });
  },

  clearWeRead(): Promise<IntegrationStatus> {
    return request('/integrations/weread', { method: 'DELETE' });
  },

  syncWeRead(limit = 50): Promise<WeReadSyncResult> {
    return request(`/integrations/weread/sync?limit=${limit}`, { method: 'POST' });
  },
};

// ─── Sources API ───

export const sourcesApi = {
  /** 获取信源列表（支持分页和筛选） */
  list(params?: {
    page?: number;
    page_size?: number;
    source_type?: string;
    status?: string;
    enabled?: boolean;
    keyword?: string;
  }): Promise<PaginatedResponse<Source> & { total?: number }> {
    const qs = new URLSearchParams();
    if (params?.page) qs.set('page', String(params.page));
    if (params?.page_size) qs.set('page_size', String(params.page_size));
    if (params?.source_type) qs.set('source_type', params.source_type);
    if (params?.status) qs.set('status', params.status);
    if (params?.enabled !== undefined) qs.set('enabled', String(params.enabled));
    if (params?.keyword) qs.set('keyword', params.keyword);
    const query = qs.toString();
    return request(`/sources${query ? '?' + query : ''}`);
  },

  /** 获取单个信源 */
  get(id: number): Promise<Source> {
    return request(`/sources/${id}`);
  },

  /** 添加信源 */
  create(data: CreateSourceRequest): Promise<Source> {
    return request('/sources', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 更新信源 */
  update(id: number, data: UpdateSourceRequest): Promise<Source> {
    return request(`/sources/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /** 保存信源排序（用于信源地图看板拖拽） */
  reorder(ordered_ids: number[]): Promise<{ message: string; updated: number }> {
    assertUniqueIds(ordered_ids, '信源排序包含重复项，请刷新后重试');
    return request('/sources/reorder', {
      method: 'POST',
      body: JSON.stringify({ ordered_ids }),
    });
  },

  /** 删除信源 */
  delete(id: number): Promise<void> {
    return request(`/sources/${id}`, { method: 'DELETE' });
  },

  /** 手动触发同步 */
  sync(id: number): Promise<SyncResult> {
    return request(`/sources/${id}/sync`, { method: 'POST' });
  },

  /** 从 OPML 文件导入 RSS 源（Folo/Follow 导出） */
  importOPML(file: File): Promise<{ created: number; skipped: number; total: number; message: string }> {
    const formData = new FormData();
    formData.append('file', file);
    const token = getAuthToken();
    return fetch(`${BASE_URL}/sources/import-opml`, {
      method: 'POST',
      body: formData,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    }).then(async (response) => {
      const text = await response.text();
      const payload = text ? JSON.parse(text) : undefined;
      if (!response.ok) {
        const detail = formatApiErrorDetail(payload?.detail);
        const message = typeof payload?.message === 'string' ? payload.message : undefined;
        throw new Error(detail || message || `API Error: ${response.status}`);
      }
      return payload;
    });
  },

  /** 预览批量信源配置 */
  previewBatchSources(data: { content: string; category?: string; enabled?: boolean; weight?: number }): Promise<{
    items: SourceBatchImportItem[];
    total: number;
    duplicates: number;
    importable: number;
  }> {
    return request('/sources/preview-batch', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 导入批量信源配置 */
  importBatchSources(data: { content: string; category?: string; enabled?: boolean; weight?: number }): Promise<{ created: number; skipped: number; total: number; message: string }> {
    return request('/sources/import-batch', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // ── /me 系列：用户私有信源（对齐 modelsApi.mine/createMine 模式）──

  /** 获取我的私有信源列表 */
  listMine(params?: {
    page?: number;
    page_size?: number;
    source_type?: string;
    status?: string;
    enabled?: boolean;
    keyword?: string;
  }): Promise<PaginatedResponse<Source> & { total?: number }> {
    const qs = new URLSearchParams();
    if (params?.page) qs.set('page', String(params.page));
    if (params?.page_size) qs.set('page_size', String(params.page_size));
    if (params?.source_type) qs.set('source_type', params.source_type);
    if (params?.status) qs.set('status', params.status);
    if (params?.enabled !== undefined) qs.set('enabled', String(params.enabled));
    if (params?.keyword) qs.set('keyword', params.keyword);
    const query = qs.toString();
    return request(`/sources/me${query ? '?' + query : ''}`);
  },

  /** 获取我的单个私有信源 */
  getMine(id: number): Promise<Source> {
    return request(`/sources/me/${id}`);
  },

  /** 创建我的私有信源 */
  createMine(data: CreateSourceRequest): Promise<Source> {
    return request('/sources/me', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 更新我的私有信源 */
  updateMine(id: number, data: UpdateSourceRequest): Promise<Source> {
    return request(`/sources/me/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /** 删除我的私有信源 */
  deleteMine(id: number): Promise<void> {
    return request(`/sources/me/${id}`, { method: 'DELETE' });
  },

  /** 手动触发我的私有信源同步 */
  syncMine(id: number): Promise<SyncResult> {
    return request(`/sources/me/${id}/sync`, { method: 'POST' });
  },
};

export interface SourceBatchImportItem {
  name: string;
  url: string;
  source_type: string;
  category: string;
  platform: string | null;
  duplicate: boolean;
}

// ─── Contents API ───

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

  /** 切换收藏状态 */
  toggleFavorite(id: number): Promise<{ is_favorited: boolean; favorite_id?: number | null }> {
    return request(`/contents/${id}/favorite`, { method: 'POST' });
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
  todayPicks(params?: { category?: string; time_range?: string; limit?: number }): Promise<{
    items: ContentItem[];
    topics: TopicInfo[];
    total: number;
    duplicates_hidden: number;
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
};

export interface ContentCategoryItem {
  id: number;
  name: string;
  description?: string | null;
  keywords: string[];
  is_auto_created: boolean;
  content_count: number;
}

export const contentCategoriesApi = {
  list(): Promise<{ categories: ContentCategoryItem[] }> {
    return request('/categories');
  },
};

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

export interface ScoringFlowStage {
  key: string;
  label: string;
  count: number;
  retention: number;
}

export interface ScoringFlowSample {
  id: number;
  title: string;
  url: string;
  source_name: string | null;
  category: string;
  summary?: string | null;
  recommendation?: string | null;
  tags?: string[];
  creator_angles?: string[];
  is_favorited?: boolean;
  selected: boolean;
  final_score: number;
  threshold_used: number;
  base_score: number;
  source_bonus: number;
  quality_factor: number;
  risk_factor: number;
  time_decay: number;
  diversity_factor: number;
  feedback_score: number;
  dimension_scores: Record<string, number>;
}

export interface ScoringFlowDiagnostics {
  analyzed_total: number;
  window_total: number;
  collected_window_total?: number;
  pending_analysis_total?: number;
  window_options: Array<{ hours: number; count: number }>;
  collected_window_options?: Array<{ hours: number; count: number }>;
  recommended_hours?: number | null;
  loaded_count: number;
  scoring_input_count: number;
  scored_count: number;
  ignored_count: number;
  candidate_limit: number;
  sample_limit: number;
  empty_reason: string;
  generated_at: string;
}

export interface ScoringFlowConfig {
  curation_mode: string;
  curation_percentile?: number;
  curation_threshold: number;
  min_selected_base_score: number;
  quality_gate_min: number;
  quality_gate_strong: number;
  quality_gate_floor: number;
  risk_threshold: number;
  risk_soft_start: number;
  risk_soft_floor: number;
  time_decay_lambda: number;
  time_decay_floor: number;
  diversity_top_n: number;
  same_source_grace: number;
  same_category_grace: number;
}

export interface ScoringFlowResponse {
  total: number;
  scored: number;
  hours: number;
  diagnostics?: ScoringFlowDiagnostics;
  scoring_config?: ScoringFlowConfig;
  stages: ScoringFlowStage[];
  samples: ScoringFlowSample[];
  category_mix: Array<{ label: string; count: number }>;
  source_mix: Array<{ label: string; count: number }>;
}

// ─── Topics API ───

// Backend returns {items: TopicGroupResponse[], total: number}
interface TopicGroupResponse {
  id: number;
  name: string;
  summary: string | null;
  keywords: string[] | null;
  content_count: number;
  best_score: number;
}

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

// ─── Daily Report API ───

export const dailyReportApi = {
  /** 获取今日日报（不存在则自动生成） */
  getToday(): Promise<Record<string, unknown>> {
    return request('/daily-reports/today');
  },

  /** 按日期查询单个日报 */
  getByDate(date: string): Promise<Record<string, unknown>> {
    return request(`/daily-reports/by-date?date=${encodeURIComponent(date)}`);
  },

  /** 获取有日报的日期列表 */
  listDates(): Promise<{ dates: Array<{ report_date: string; weekday: string; takeaway: string | null; status: string }> }> {
    return request('/daily-reports/dates');
  },

  /** 获取最近一段时间的日报状态地图 */
  calendar(days: number = 30): Promise<{
    days: Array<{
      report_date: string;
      weekday: string;
      status: string;
      edition: string | null;
      generated_at: string | null;
      cutoff_at: string | null;
      takeaway: string | null;
      content_count: number;
      analyzed_count: number;
      topic_count: number;
      has_report: boolean;
      can_generate: boolean;
      is_today: boolean;
    }>;
    total_days: number;
    done_count: number;
    error_count: number;
    missing_count: number;
    generating_count: number;
  }> {
    return request(`/daily-reports/calendar?days=${days}`);
  },

  /** 日报列表 */
  list(limit: number = 7): Promise<{ items: Record<string, unknown>[]; total: number }> {
    return request(`/daily-reports?limit=${limit}`);
  },

  /** 强制重新生成今日日报 */
  regenerate(): Promise<Record<string, unknown>> {
    return request('/daily-reports/generate', { method: 'POST' });
  },

  /** 生成指定日报版本 */
  generateVersion(params: { target_date?: string; edition?: string; cutoff_at?: string; force?: boolean } = {}): Promise<Record<string, unknown>> {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => [k, String(v)])
    ).toString();
    return request(`/daily-reports/generate-version${query ? `?${query}` : ''}`, { method: 'POST' });
  },

  // ── /me series: user-owned private daily reports (T2) ──

  /** 获取今日我的专属日报（不存在则自动生成；需 Pro+） */
  getMyToday(): Promise<Record<string, unknown>> {
    return request('/daily-reports/me/today');
  },

  /** 按日期查询我的日报 */
  getMyByDate(date: string): Promise<Record<string, unknown>> {
    return request(`/daily-reports/me/by-date?date=${encodeURIComponent(date)}`);
  },

  /** 获取我的日报日期列表 */
  listMyDates(): Promise<{ dates: Array<{ report_date: string; weekday: string; takeaway: string | null; status: string }> }> {
    return request('/daily-reports/me/dates');
  },

  /** 强制重新生成我的今日日报 */
  regenerateMy(): Promise<Record<string, unknown>> {
    return request('/daily-reports/me/generate', { method: 'POST' });
  },
};

export const creationApi = {
  /** 生成创作方案 */
  generatePlan(contentId: number, platform: string): Promise<Record<string, unknown>> {
    return request('/creation/plan', {
      method: 'POST',
      body: JSON.stringify({ content_id: contentId, platform }),
    });
  },

  /** 获取可用平台列表 */
  listPlatforms(): Promise<Record<string, unknown>> {
    return request('/creation/platforms');
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

// ─── Settings API ───

export const settingsApi = {
  /** 获取 RSSHub 实例列表 */
  getRSSHubInstances(): Promise<{ instances: RSSHubInstance[]; default_instances: string[] }> {
    return request('/settings/rsshub/instances');
  },

  /** 更新 RSSHub 实例列表 */
  updateRSSHubInstances(instances: RSSHubInstance[]): Promise<{ instances: RSSHubInstance[]; updated: boolean }> {
    return request('/settings/rsshub/instances', {
      method: 'PUT',
      body: JSON.stringify({ instances }),
    });
  },
};

// ─── Stats / Dashboard API ───

export const statsApi = {
  /** 内容总览 */
  getOverview(days = 7): Promise<StatsOverview> {
    return request(`/stats/overview?days=${days}`);
  },

  /** 信源分布 */
  getSourceDistribution(days = 7): Promise<{ sources: StatsSourceItem[] }> {
    return request(`/stats/source-distribution?days=${days}`);
  },

  /** 分类分布 */
  getCategoryDistribution(days = 7): Promise<{ categories: StatsCategoryItem[] }> {
    return request(`/stats/category-distribution?days=${days}`);
  },

  /** 时间趋势 */
  getDailyTrend(days = 7): Promise<{ trend: StatsTrendItem[] }> {
    return request(`/stats/daily-trend?days=${days}`);
  },

  /** 网文平台统计 */
  getNovelPlatforms(): Promise<{ platforms: StatsNovelPlatform[] }> {
    return request('/stats/novel-platforms');
  },

  /** Aggregated stats workspace payload, with legacy dashboard fields included */
  getDashboard(days = 7): Promise<StatsDashboard> {
    return request(`/stats/dashboard?days=${days}`);
  },
};

// ─── Job execution stats (job_execution_logs 聚合) ───

export const statsJobsApi = {
  get(days = 7, jobKey?: string): Promise<JobStatsResponse> {
    const params = new URLSearchParams();
    params.set('days', String(days));
    if (jobKey) params.set('job_key', jobKey);
    return request(`/stats/jobs?${params.toString()}`);
  },
};

// ─── Trends API ───

export interface TrendPoint {
  date: string;
  topic_id: number;
  topic_name: string;
  content_count: number;
  avg_score: number;
  max_score: number;
  pick_count: number;
  top_items: { title: string; url: string; score: number }[] | null;
}

export interface TrendKeywordItem {
  keyword: string;
  count: number;
}

export const trendsApi = {
  /** Topic trend curves for the last N days */
  topics(days = 7): Promise<{ days: number; trends: TrendPoint[] }> {
    return request(`/trends/topics?days=${days}`);
  },

  /** Keyword frequency for trend workspace visualizations */
  keywords(params?: { days?: number; limit?: number }): Promise<{ days: number; keywords: TrendKeywordItem[] }> {
    const days = params?.days ?? 7;
    const limit = params?.limit ?? 50;
    return request(`/trends/keywords?days=${days}&limit=${limit}`);
  },
};

// ─── Feedback API ───

export const feedbackApi = {
  /** 提交反馈 */
  submit(contentId: number, feedbackType: FeedbackType, comment?: string): Promise<Record<string, unknown>> {
    return request('/feedback', {
      method: 'POST',
      body: JSON.stringify({ content_id: contentId, feedback_type: feedbackType, comment }),
    });
  },

  /** 获取内容的反馈列表 */
  list(contentId: number): Promise<Record<string, unknown>[]> {
    return request(`/feedback/content/${contentId}`);
  },

  /** 获取反馈统计 */
  stats(): Promise<{ total: number; by_type: Record<string, number>; avg_score_delta: number }> {
    return request('/feedback/stats');
  },
};

// ─── Product Feedback / Updates API ───

export type IssueFeedbackSeverity = 'low' | 'medium' | 'high' | 'critical';
export type IssueFeedbackStatus = 'open' | 'triaged' | 'in_progress' | 'fixed' | 'closed';
export type ProductUpdateKind = 'roadmap' | 'release' | 'fix' | 'improvement';
export type ProductUpdateStatus = 'planned' | 'in_progress' | 'shipped';

export interface IssueFeedbackItem {
  id: number;
  user_id: number | null;
  title: string;
  description: string;
  area: string;
  severity: IssueFeedbackSeverity;
  status: IssueFeedbackStatus;
  resolution_note?: string | null;
  fixed_at?: string | null;
  created_at: string;
  updated_at: string;
  reporter_email?: string | null;
  reporter_name?: string | null;
}

export interface IssueFeedbackListResponse {
  items: IssueFeedbackItem[];
  total: number;
  open_count: number;
  fixed_count: number;
}

export interface ProductUpdateEntry {
  title: string;
  description: string;
  kind: ProductUpdateKind;
}

export interface ProductUpdateItem {
  /** 1 个版本 = 1 记录; items[] 装该版本的全部更新 */
  id: number;
  version: string;
  status: ProductUpdateStatus;
  target_date?: string | null;
  shipped_at?: string | null;
  items: ProductUpdateEntry[];
  created_by_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProductUpdateListResponse {
  items: ProductUpdateItem[];
  total: number;
}

export const productFeedbackApi = {
  createIssue(data: {
    title: string;
    description: string;
    area?: string;
    severity?: IssueFeedbackSeverity;
  }): Promise<IssueFeedbackItem> {
    return request('/product-feedback/issues', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  listMine(params?: { status?: IssueFeedbackStatus | ''; limit?: number; offset?: number }): Promise<IssueFeedbackListResponse> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== '')
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/product-feedback/issues/mine${query}`);
  },

  listIssues(params?: {
    status?: IssueFeedbackStatus | '';
    severity?: IssueFeedbackSeverity | '';
    area?: string;
    limit?: number;
    offset?: number;
  }): Promise<IssueFeedbackListResponse> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== '')
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/product-feedback/issues${query}`);
  },

  updateIssue(id: number, data: {
    status?: IssueFeedbackStatus;
    severity?: IssueFeedbackSeverity;
    area?: string;
    resolution_note?: string | null;
  }): Promise<IssueFeedbackItem> {
    return request(`/product-feedback/issues/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  listUpdates(params?: {
    kind?: ProductUpdateKind | '';
    status?: ProductUpdateStatus | '';
    limit?: number;
    offset?: number;
  }): Promise<ProductUpdateListResponse> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== '')
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/product-feedback/updates${query}`);
  },

  createUpdate(data: {
    version: string;
    status: ProductUpdateStatus;
    target_date?: string | null;
    shipped_at?: string | null;
    items: ProductUpdateEntry[];
  }): Promise<ProductUpdateItem> {
    return request('/product-feedback/updates', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  updateProductUpdate(id: number, data: Partial<{
    version: string;
    status: ProductUpdateStatus;
    target_date: string | null;
    shipped_at: string | null;
    items: ProductUpdateEntry[];
  }>): Promise<ProductUpdateItem> {
    return request(`/product-feedback/updates/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  deleteProductUpdate(id: number): Promise<void> {
    return request(`/product-feedback/updates/${id}`, { method: 'DELETE' });
  },
};

// ─── Weekly Digest (周刊) API ───

export const weeklyDigestApi = {
  /** 获取本周周刊（不存在则自动生成） */
  getCurrent(): Promise<WeeklyDigest> {
    return request('/weekly-digests/current');
  },

  /** 按 week_key 获取周刊 */
  getByWeek(weekKey: string): Promise<WeeklyDigest> {
    return request(`/weekly-digests/by-week?week_key=${encodeURIComponent(weekKey)}`);
  },

  /** 获取所有有周刊的周列表 */
  listWeeks(): Promise<WeeklyDigestWeeksResponse> {
    return request('/weekly-digests/weeks');
  },

  /** 获取周刊列表 */
  list(limit: number = 8): Promise<WeeklyDigestListResponse> {
    return request(`/weekly-digests?limit=${limit}`);
  },

  /** 强制重新生成周刊 */
  generate(weekKey?: string): Promise<WeeklyDigest> {
    const query = weekKey ? `?week_key=${encodeURIComponent(weekKey)}` : '';
    return request(`/weekly-digests/generate${query}`, { method: 'POST' });
  },
};

// ─── Monthly Digest (月刊) API ───

export const monthlyDigestApi = {
  /** 获取最新完整月刊（不存在则自动生成） */
  getCurrent(): Promise<MonthlyDigest> {
    return request('/monthly-digests/current');
  },

  /** 按 month_key 获取月刊 */
  getByMonth(monthKey: string): Promise<MonthlyDigest> {
    return request(`/monthly-digests/by-month?month_key=${encodeURIComponent(monthKey)}`);
  },

  /** 获取所有有月刊的月份列表 */
  listMonths(): Promise<MonthlyDigestMonthsResponse> {
    return request('/monthly-digests/months');
  },

  /** 获取月刊列表 */
  list(limit: number = 12): Promise<MonthlyDigestListResponse> {
    return request(`/monthly-digests?limit=${limit}`);
  },

  /** 强制重新生成月刊 */
  generate(monthKey?: string): Promise<MonthlyDigest> {
    const query = monthKey ? `?month_key=${encodeURIComponent(monthKey)}` : '';
    return request(`/monthly-digests/generate${query}`, { method: 'POST' });
  },
};

// ─── Trending Radar (趋势雷达) API ───

export interface TrendingItem {
  id: number;
  source: string;
  category: string;
  rank: number;
  title: string;
  url: string;
  hot_value: number;
  hot_value_raw: string;
  trend: string | null;
  cover_url: string | null;
  extra: Record<string, unknown> | null;
  fetched_at: string;
  batch_id: string;
}

export interface TrendingSource {
  source: string;
  category: string;
  display_name: string;
  count: number;
  last_synced: string | null;
}

export interface TrendingAngleRecommendation {
  common_angles: string[];
  contrast_angles: { angle: string; reasoning: string }[];
  angle_note: string;
}

export const trendingApi = {
  /** 获取趋势数据 */
  list(params?: {
    category?: string;
    source?: string;
    exclude_sources?: string[];
    limit?: number;
  }): Promise<TrendingItem[]> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined && v !== '' && !(Array.isArray(v) && v.length === 0))
            .map(([k, v]) => [k, Array.isArray(v) ? v.join(',') : String(v)])
        ).toString()
      : '';
    return request(`/trending${query}`);
  },

  /** 获取可用信源列表 */
  async listSources(): Promise<TrendingSource[]> {
    const data = await request<TrendingSource[] | { sources?: TrendingSource[] }>('/trending/sources');
    return Array.isArray(data) ? data : data.sources || [];
  },

  /** 同步单个信源 */
  sync(source: string): Promise<{ fetched: number }> {
    return request(`/trending/sync/${encodeURIComponent(source)}`, { method: 'POST' });
  },

  /** 同步所有信源 */
  syncAll(): Promise<Record<string, { fetched: number }>> {
    return request('/trending/sync-all', { method: 'POST' });
  },

  /** 跨平台热点交叉发现 */
  crossPlatform(params?: { min_resonance?: number; limit?: number }): Promise<{
    total: number;
    clusters: CrossPlatformCluster[];
  }> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/trending/cross-platform${query}`);
  },

  /** 持续在榜话题分析 */
  persistent(params?: { min_days?: number; min_sources?: number; days_back?: number }): Promise<{
    total: number;
    topics: PersistentTopic[];
  }> {
    const query = params
      ? '?' + new URLSearchParams(
          Object.entries(params)
            .filter(([, v]) => v !== undefined)
            .map(([k, v]) => [k, String(v)])
        ).toString()
      : '';
    return request(`/trending/persistent${query}`);
  },

  /** 为共振话题生成创作角度推荐 */
  angles(topic: string): Promise<TrendingAngleRecommendation> {
    return request(`/trending/angles?topic=${encodeURIComponent(topic)}`);
  },
};

// ─── Cross-Platform Clustering ───

export interface PersistentTopic {
  title: string;
  days_on_list: number;
  total_days: number;
  snapshot_count: number;
  sources: string[];
  source_count: number;
  avg_rank: number;
  best_rank: number;
  hot_value_max: number;
  rank_trend: number[];
  first_seen: string;
  last_seen: string;
}

export interface CrossPlatformSourceItem {
  source: string;
  source_label: string;
  title: string;
  rank: number;
  hot_value: number;
  hot_value_raw: string;
  url: string;
  trend: string | null;
}

export interface CrossPlatformCluster {
  topic: string;
  keywords: string[];
  resonance: number;
  item_count: number;
  sources: string[];
  source_labels: string[];
  source_items: CrossPlatformSourceItem[];
  total_hot: number;
  avg_rank: number;
}

// ─── Mother Topics API ──────────────────────────────────────────────

export interface MotherTopic {
  id: number;
  name: string;
  description: string | null;
  keywords: string[];
  weight: number;
  content_type: string | null;
  target_reader: string | null;
  is_active: boolean;
  display_order: number;
  created_at: string | null;
  updated_at: string | null;
}

export type MotherTopicMutation = Partial<
  Pick<
    MotherTopic,
    | 'name'
    | 'description'
    | 'keywords'
    | 'weight'
    | 'content_type'
    | 'target_reader'
    | 'is_active'
    | 'display_order'
  >
>;

export interface ContentScoringResult {
  title: string;
  topic_scores: Array<{
    name: string;
    keyword_score: number;
    weight: number;
    freshness: number;
    final: number;
  }>;
  top_topic: string | null;
  final_score: number;
}

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

export interface FanqieCategory {
  fanqie_id: string;
  name: string;
  group: 'male' | 'female';
}

export interface FanqieBook {
  book_id: string;
  url: string;
  book_name: string;
  author: string;
  abstract: string;
  thumb_uri: string;
  read_count: string;
  word_number: string;
  last_chapter_title: string;
  position: number;
  rank_type: string;
  rank_pos_diff?: number | null;
}

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

export interface WebnovelMovementItem {
  platform: 'fanqie' | 'qimao' | 'zhihu' | 'heiyan' | 'ishugui';
  platform_label: string;
  title: string;
  author: string;
  category: string;
  rank_type: string;
  position: number;
  change: number;
  url: string | null;
}

export interface WebnovelCategoryItem {
  category: string;
  count: number;
}

export interface WebnovelWeeklyReport {
  period: {
    start: string;
    end: string;
    days: number;
    label: string;
  };
  generated_at: string;
  summary: {
    total_items: number;
    snapshot_days: number;
    rising_count: number;
    falling_count: number;
    read_count_delta: number;
  };
  platforms: Array<{
    platform: 'fanqie' | 'qimao' | 'zhihu' | 'heiyan' | 'ishugui';
    label: string;
    item_count: number;
    rising_count: number;
    falling_count: number;
    history_days: number;
  }>;
  daily_counts: Array<{ date: string; count: number }>;
  top_risers: WebnovelMovementItem[];
  top_fallers: WebnovelMovementItem[];
  category_mix: Record<string, WebnovelCategoryItem[]>;
  notes: string[];
}

export const webnovelReportsApi = {
  weekly(days = 7): Promise<WebnovelWeeklyReport> {
    return request(`/webnovel/reports/weekly?days=${days}`);
  },
};

// ─── 知乎盐选 API ──────────────────────────────────...

// ─── 七猫小说 API ────────────────────────────────────────────────────────────

export interface QimaoBook {
  book_id: string;
  url: string;
  title: string;
  author: string;
  abstract: string;
  category1_name: string;
  category2_name: string;
  thumb_uri: string;
  words_num: string;
  collect_count: number;
  latest_chapter_title: string;
  update_time: string;
  is_over: number;
  is_continue_top: number;
  index_change: number;
  position: number;
  rank_type?: string;
}

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

export interface ZhihuAlbum {
  business_id: string;
  title: string;
  author: string;
  author_desc: string | null;
  abstract: string | null;
  thumb_url: string | null;
  chapter_text: string | null;
  price_yuan: string;
  price: number;
  is_exclusive: boolean;
  is_svip: boolean;
  online_time_text: string | null;
  tag: string | null;
  category1_name: string;
  category2_name: string | null;
  position: number;
  rank_pos_diff: number | null;
  url: string;
  sort_type: string;
}

export interface ZhihuCategory {
  zhihu_id: string;
  name: string;
  name_en: string | null;
  level: number;
  parent_id: string | null;
  sort: number;
  artwork: string | null;
}

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

// ─── LLM Models API ───

export interface LlmModelItem {
  id: number;
  owner_user_id?: number | null;
  scope?: string;
  name: string;
  provider: string;
  model_id: string;
  resolved_model: string;
  api_base: string | null;
  api_key_set: boolean;
  enabled: boolean;
  routing_group: string;
  model_family: string | null;
  channel_name: string | null;
  routing_priority: number;
  cooldown_seconds: number;
  temperature: number;
  max_tokens: number;
  requests_per_minute: number;
  description: string | null;
  cost_per_1k_input: number | null;
  cost_per_1k_output: number | null;
  cost_per_1m_input: number | null;
  cost_per_1m_input_cache_hit: number | null;
  cost_per_1m_output: number | null;
  extra_params: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface LlmModelPresetItem {
  key: string;
  label: string;
  provider: string;
  model_id: string;
  model_id_placeholder?: string | null;
  api_base?: string | null;
  api_base_placeholder?: string | null;
  model_family?: string | null;
  channel_name?: string | null;
  description: string;
  recommended_for: string[];
  requires: string[];
  help: string;
  defaults: Record<string, unknown>;
}

export interface LlmModelPresetCatalog {
  defaults: Record<string, unknown>;
  parameter_help?: Record<string, {
    label: string;
    default: unknown;
    range?: number[];
    unit?: string;
    recommended?: string;
    plain: string;
    beginner?: string;
    when_to_change?: string[];
  }>;
  presets: LlmModelPresetItem[];
  help: Record<string, string>;
}

export interface MyLlmModelsResponse {
  models: LlmModelItem[];
  total: number;
  custom_ai_allowed: boolean;
}

export type LlmModelCreatePayload = Partial<LlmModelItem> & {
  api_key?: string;
  preset_key?: string;
  cost_per_1m_input?: number | null;
  cost_per_1m_input_cache_hit?: number | null;
  cost_per_1m_output?: number | null;
};

export interface EvalRun {
  eval_run_id: string;
  prompt_type: string;
  model_count: number;
  created_at: string | null;
  done_count: number;
  fail_count: number;
}

export interface EvalResult {
  id: number;
  model_id: number;
  model_name: string;
  status: string;
  response_text: string | null;
  duration_ms: number;
  tokens_input: number | null;
  tokens_output: number | null;
  quality_score: number | null;
  auto_score: number | null;
  notes: string | null;
  error_message: string | null;
  created_at: string | null;
}

export interface ModelUsageBucket {
  calls: number;
  success_calls: number;
  failed_calls: number;
  tokens_input: number;
  tokens_output: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  billable_input_tokens: number;
  estimated_cost: number;
}

export interface ModelUsageByModel extends ModelUsageBucket {
  model_id: number;
  model_name: string;
  provider: string | null;
  avg_duration_ms: number;
  cost_per_1k_input: number | null;
  cost_per_1k_output: number | null;
  cost_per_1m_input?: number | null;
  cost_per_1m_input_cache_hit?: number | null;
  cost_per_1m_output?: number | null;
}

export interface ModelUsageByPrompt extends ModelUsageBucket {
  prompt_type: string;
}

export interface ModelUsageSummary {
  days: number;
  since: string;
  total: ModelUsageBucket & {
    tokens_total: number;
    avg_duration_ms: number;
    success_rate: number;
  };
  by_model: ModelUsageByModel[];
  by_prompt: ModelUsageByPrompt[];
}

export const modelsApi = {
  list(): Promise<{ models: LlmModelItem[]; total: number }> {
    return request('/models');
  },
  mine(): Promise<MyLlmModelsResponse> {
    return request('/models/me');
  },
  presets(): Promise<LlmModelPresetCatalog> {
    return request('/models/presets');
  },
  usageSummary(days = 30): Promise<ModelUsageSummary> {
    return request(`/models/usage/summary?days=${days}`);
  },
  create(data: LlmModelCreatePayload): Promise<{ id: number; name: string; message: string }> {
    return request('/models', { method: 'POST', body: JSON.stringify(data) });
  },
  update(id: number, data: Partial<LlmModelItem> & { api_key?: string }): Promise<{ message: string }> {
    return request(`/models/${id}`, { method: 'PUT', body: JSON.stringify(data) });
  },
  delete(id: number): Promise<{ message: string }> {
    return request(`/models/${id}`, { method: 'DELETE' });
  },
  createMine(data: LlmModelCreatePayload): Promise<{ id: number; name: string; message: string }> {
    return request('/models/me', { method: 'POST', body: JSON.stringify(data) });
  },
  updateMine(id: number, data: Partial<LlmModelItem> & { api_key?: string }): Promise<{ message: string }> {
    return request(`/models/me/${id}`, { method: 'PUT', body: JSON.stringify(data) });
  },
  deleteMine(id: number): Promise<{ message: string }> {
    return request(`/models/me/${id}`, { method: 'DELETE' });
  },
  test(id: number): Promise<{ status: string; model_name: string; response?: string; error?: string; duration_ms: number; tokens_input?: number; tokens_output?: number; cache_read_tokens?: number; cache_creation_tokens?: number }> {
    return request(`/models/${id}/test`, { method: 'POST' });
  },
  runEvaluation(data: { model_ids: number[]; prompt_type: string; custom_prompt?: string; sample_content?: string }): Promise<{ eval_run_id: string; model_count: number; message: string }> {
    return request('/models/evaluations/run', { method: 'POST', body: JSON.stringify(data) });
  },
  listEvalRuns(limit?: number): Promise<{ runs: EvalRun[]; total: number }> {
    const qs = limit ? `?limit=${limit}` : '';
    return request(`/models/evaluations/runs${qs}`);
  },
  getEvalRun(runId: string): Promise<{ eval_run_id: string; prompt_type: string; results: EvalResult[] }> {
    return request(`/models/evaluations/runs/${runId}`);
  },
  scoreEvaluation(evalId: number, quality_score: number, notes?: string): Promise<{ message: string }> {
    return request(`/models/evaluations/${evalId}/score`, { method: 'PUT', body: JSON.stringify({ quality_score, notes }) });
  },
};
