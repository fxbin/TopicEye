/**
 * _domains API objects extracted from lib/api.ts.
 * Uses request from ./_core.
 */

import { request } from './_core';
import type { ContentCategoryItem, ScoringFlowResponse } from '@/types/contents';
import type { ArticleReaderSnapshot, ContentItem, ContentAnalysis, ContentRelation, EvidenceMark, EvidenceLink, PaginatedResponse, SyncResult, TopicInfo, TopicFilterParams, ContentFilterParams, FavoriteItem, FavoriteStatus, FavoriteTargetType, YesterdayTrackingData } from '@/types';
import type { FavoriteCreatePayload, FavoriteTargetState } from '@/lib/favorites';
import type { Source, CreateSourceRequest, UpdateSourceRequest } from '@/types';
import { assertUniqueIds, chunkArray, BASE_URL, formatApiErrorDetail, FAVORITE_STATE_BATCH_SIZE } from './_core';
import type { TopicGroupResponse } from '@/types/contents';

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

  /** 获取信源的来源证据画像 */
  getEvidenceProfile(id: number): Promise<{
    source_id: number;
    profile: {
      publisher_identity: string;
      publisher_family: string;
      platform: string;
      publisher_kind: string;
      official_domains: string[];
      verification_proof_url: string | null;
      reviewed_at: string | null;
    } | null;
  }> {
    return request(`/sources/${id}/evidence-profile`);
  },

  /** 创建或更新信源的来源证据画像 */
  upsertEvidenceProfile(id: number, data: {
    publisher_identity: string;
    publisher_family: string;
    platform: string;
    publisher_kind: string;
    official_domains?: string[];
    verification_proof_url?: string;
  }): Promise<{ source_id: number; updated: boolean }> {
    return request(`/sources/${id}/evidence-profile`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /** 从 OPML 文件导入 RSS 源（Folo/Follow 导出） */
  importOPML(file: File): Promise<{ created: number; skipped: number; total: number; message: string }> {
    const formData = new FormData();
    formData.append('file', file);
    return fetch(`${BASE_URL}/sources/import-opml`, {
      method: 'POST',
      body: formData,
      credentials: 'include',
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

  /** 获取我的私有信源列表（含配额信息） */
  listMine(params?: {
    page?: number;
    page_size?: number;
    source_type?: string;
    status?: string;
    enabled?: boolean;
    keyword?: string;
  }): Promise<PaginatedResponse<Source> & {
    total?: number;
    private_sources_used?: number | null;
    private_sources_quota?: number | null;
  }> {
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

  /** 根据粘贴的 URL 推断信源类型（创建私有信源时的 UX 辅助） */
  recognizeMine(url: string, name?: string): Promise<{
    source_type: string;
    normalized_url: string;
    extra_config: Record<string, unknown> | null;
  }> {
    const qs = new URLSearchParams({ url });
    if (name) qs.set('name', name);
    return request(`/sources/me/recognize?${qs.toString()}`);
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
  todayPicks(params?: { category?: string; time_range?: string; limit?: number }): Promise<{
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

// ─── Daily Report API ───

export interface WebhookDeliveryLogItem {
  id: number;
  alert_key: string;
  event_type: string;
  title: string;
  severity: string;
  webhook_url_preview: string;
  status_code: number | null;
  success: boolean;
  error_message: string | null;
  response_preview: string | null;
  duration_ms: number;
  created_at: string | null;
}

export const dailyReportApi = {
  /** 获取今日日报（不存在则自动生成） */
  getToday(): Promise<Record<string, unknown>> {
    return request('/daily-reports/today');
  },

  /** 按日期查询单个日报 */
  getByDate(date: string): Promise<Record<string, unknown>> {
    return request(`/daily-reports/by-date?date=${encodeURIComponent(date)}`);
  },

  /** 选题 sparkline 趋势数据（按标题关键词查询近 N 小时内容流入速率） */
  sparkline(title: string, hours: number = 48, bucketHours: number = 2): Promise<{
    points: Array<{ ts: string; count: number; baseline?: number }>;
    keywords: string[];
    total: number;
    window_hours: number;
  }> {
    return request(
      `/daily-reports/sparkline?title=${encodeURIComponent(title)}&hours=${hours}&bucket_hours=${bucketHours}`,
    );
  },

  /** 获取用户的选题标记 */
  listPickMarks(reportDate?: string): Promise<{
    marks: Array<{
      report_date: string;
      pick_title: string;
      action: 'write' | 'watch' | 'skip';
      pick_category: string | null;
      pick_source_url: string | null;
    }>;
    total: number;
  }> {
    return request(
      `/daily-reports/pick-marks${reportDate ? `?report_date=${reportDate}` : ''}`,
    );
  },

  /** 创建/更新选题标记 */
  markPick(body: {
    report_date: string;
    pick_title: string;
    action: 'write' | 'watch' | 'skip';
    pick_category?: string;
    pick_source_url?: string;
  }): Promise<{ status: string; action: string }> {
    return request('/daily-reports/pick-marks', { method: 'POST', body: JSON.stringify(body) });
  },

  /** 删除选题标记 */
  unmarkPick(reportDate: string, pickTitle: string): Promise<{ status: string }> {
    return request(
      `/daily-reports/pick-marks?report_date=${encodeURIComponent(reportDate)}&pick_title=${encodeURIComponent(pickTitle)}`,
      { method: 'DELETE' },
    );
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

  /** 手动推送日报到 webhook（管理员） */
  pushWebhook(date: string, edition?: string): Promise<{ sent: boolean; message: string }> {
    const params = new URLSearchParams({ date });
    if (edition) params.set('edition', edition);
    return request(`/daily-reports/push-webhook?${params}`, { method: 'POST' });
  },

  /** 获取 webhook 推送日志（管理员） */
  listWebhookLogs(params?: { event_type?: string; limit?: number; offset?: number }): Promise<{
    items: WebhookDeliveryLogItem[];
    total: number;
    limit: number;
    offset: number;
  }> {
    const qs = new URLSearchParams();
    if (params?.event_type) qs.set('event_type', params.event_type);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const query = qs.toString();
    return request(`/daily-reports/webhook-logs${query ? '?' + query : ''}`);
  },

  /** 昨日追踪（公共日报）：昨日 top picks 的 24h 热度 delta + lifecycle 验证 */
  getYesterdayTracking(reportDate: string): Promise<YesterdayTrackingData> {
    return request(`/daily-reports/yesterday-tracking?report_date=${encodeURIComponent(reportDate)}`);
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

  /** 昨日追踪（我的日报，Pro+）：额外返回 your_marked（昨日 write/watch 标记的今日进展） */
  getMyYesterdayTracking(reportDate: string): Promise<YesterdayTrackingData> {
    return request(`/daily-reports/me/yesterday-tracking?report_date=${encodeURIComponent(reportDate)}`);
  },
};

export const creationApi = {
  /** 生成创作方案（快速模式） */
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

  /** 探索期：假设挑战 + 方向生成（探索模式 Step 1） */
  exploreDirections(contentId: number): Promise<Record<string, unknown>> {
    return request('/creation/explore', {
      method: 'POST',
      body: JSON.stringify({ content_id: contentId }),
    });
  },

  /** 聚焦期：苏格拉底追问（探索模式 Step 2） */
  focusQuestions(params: {
    content_id: number;
    selected_direction: string;
    unique_value?: string;
    pitfall?: string;
    focus_round: number;
    previous_qa?: Array<Record<string, unknown>>;
    user_redirect?: string;
  }): Promise<Record<string, unknown>> {
    return request('/creation/focus', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  /** 收敛期：结构化方案输出（探索模式 Step 3） */
  convergePlan(params: {
    content_id: number;
    platform: string;
    selected_direction: string;
    focus_answers: Array<Record<string, unknown>>;
  }): Promise<Record<string, unknown>> {
    return request('/creation/converge', {
      method: 'POST',
      body: JSON.stringify(params),
    });
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
