/**
 * _analytics API objects extracted from lib/api.ts.
 * Uses request from ./_core.
 */

import { request } from './_core';
export type FeedbackType = 'like' | 'dislike' | 'skip' | 'not_relevant' | 'outdated' | 'great_pick';
import type { IssueFeedbackItem, IssueFeedbackListResponse, IssueFeedbackSeverity, IssueFeedbackStatus, ProductUpdateEntry, ProductUpdateItem, ProductUpdateKind, ProductUpdateListResponse, ProductUpdateStatus } from '@/types/product-feedback';
import type { JobStatsByJobKey, JobStatsResponse, RSSHubInstance, StatsCategoryItem, StatsDashboard, StatsNovelPlatform, StatsOverview, StatsSourceItem, StatsTrendItem } from '@/types/stats';
import type { TrendKeywordItem, TrendPoint } from '@/types/trends';

/** 邮件 Provider 配置响应（api_key / smtp_password 脱敏） */
export interface EmailProviderConfig {
  provider: string;
  from_email: string;
  from_name: string;
  api_key_configured: boolean;
  api_key_preview: string;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password_configured: boolean;
  smtp_password_preview: string;
  smtp_use_ssl: boolean;
  supported_providers: string[];
}

/** 邮件 Provider 配置更新请求。api_key / smtp_password 为空时保留原值 */
export interface EmailProviderConfigUpdate {
  provider: string;
  from_email: string;
  from_name: string;
  api_key: string;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;
  smtp_use_ssl: boolean;
}

/** 通知推送 webhook 配置响应（webhook_url 脱敏） */
export interface NotificationWebhookConfig {
  enabled: boolean;
  webhook_url_configured: boolean;
  webhook_url_preview: string;
  note: string;
}

/** 通知推送 webhook 配置更新请求。webhook_url 为空时保留原值 */
export interface NotificationWebhookConfigUpdate {
  enabled: boolean;
  webhook_url: string;
  note: string;
}

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

  /** 获取功能模块开关（管理员） */
  getFeatureFlags(): Promise<{ flags: Record<string, boolean>; defaults: Record<string, boolean> }> {
    return request('/settings/feature-flags');
  },

  /** 更新功能模块开关（管理员，upsert 合并） */
  updateFeatureFlags(flags: Record<string, boolean>): Promise<{ flags: Record<string, boolean> }> {
    return request('/settings/feature-flags', {
      method: 'PUT',
      body: JSON.stringify({ flags }),
    });
  },

  /** 获取邮件 Provider 配置（api_key 脱敏） */
  getEmailProvider(): Promise<EmailProviderConfig> {
    return request('/settings/email-provider');
  },

  /** 更新邮件 Provider 配置。api_key 为空时保留原值 */
  updateEmailProvider(data: EmailProviderConfigUpdate): Promise<{ updated: boolean }> {
    return request('/settings/email-provider', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /** 获取通知推送 webhook 配置（webhook_url 脱敏） */
  getNotificationWebhook(): Promise<NotificationWebhookConfig> {
    return request('/settings/notification-webhook');
  },

  /** 更新通知推送 webhook 配置。webhook_url 为空时保留原值 */
  updateNotificationWebhook(data: NotificationWebhookConfigUpdate): Promise<{ updated: boolean }> {
    return request('/settings/notification-webhook', {
      method: 'PUT',
      body: JSON.stringify(data),
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

