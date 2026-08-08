/**
 * Sources API — 信源管理。
 *
 * 从 _domains.ts 拆出。
 */

import { request } from './_core';
import type { PaginatedResponse, SyncResult } from '@/types';
import type { Source, CreateSourceRequest, UpdateSourceRequest } from '@/types';
import { assertUniqueIds, BASE_URL, formatApiErrorDetail } from './_core';

export interface SourceBatchImportItem {
  name: string;
  url: string;
  source_type: string;
  category: string;
  platform: string | null;
  duplicate: boolean;
}

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
