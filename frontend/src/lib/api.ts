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
import type {
  ContentCategoryItem,
  ScoringFlowStage,
  ScoringFlowSample,
  ScoringFlowDiagnostics,
  ScoringFlowConfig,
  ScoringFlowResponse,
  TopicGroupResponse,
} from '@/types/contents';
import type { TrendPoint, TrendKeywordItem } from '@/types/trends';
import type {
  IssueFeedbackSeverity,
  IssueFeedbackStatus,
  ProductUpdateKind,
  ProductUpdateStatus,
  IssueFeedbackItem,
  IssueFeedbackListResponse,
  ProductUpdateEntry,
  ProductUpdateItem,
  ProductUpdateListResponse,
} from '@/types/product-feedback';
import type {
  TrendingItem,
  TrendingSource,
  TrendingAngleRecommendation,
  PersistentTopic,
  CrossPlatformSourceItem,
  CrossPlatformCluster,
  MotherTopic,
  MotherTopicMutation,
  ContentScoringResult,
} from '@/types/trending';
import type {
  FanqieCategory,
  FanqieBook,
  WebnovelMovementItem,
  WebnovelCategoryItem,
  WebnovelWeeklyReport,
  QimaoBook,
  ZhihuAlbum,
  ZhihuCategory,
} from '@/types/webnovel';
import type {
  LlmModelItem,
  LlmModelPresetItem,
  LlmModelPresetCatalog,
  LlmModelCreatePayload,
  EvalRun,
  EvalResult,
  ModelUsageBucket,
  ModelUsageByModel,
  ModelUsageByPrompt,
  ModelUsageSummary,
} from '@/types/models';

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
  ContentCategoryItem,
  ScoringFlowStage,
  ScoringFlowSample,
  ScoringFlowDiagnostics,
  ScoringFlowConfig,
  ScoringFlowResponse,
  TopicGroupResponse,
  TrendPoint,
  TrendKeywordItem,
  IssueFeedbackSeverity,
  IssueFeedbackStatus,
  ProductUpdateKind,
  ProductUpdateStatus,
  IssueFeedbackItem,
  IssueFeedbackListResponse,
  ProductUpdateEntry,
  ProductUpdateItem,
  ProductUpdateListResponse,
  TrendingItem,
  TrendingSource,
  TrendingAngleRecommendation,
  PersistentTopic,
  CrossPlatformSourceItem,
  CrossPlatformCluster,
  MotherTopic,
  MotherTopicMutation,
  ContentScoringResult,
  FanqieCategory,
  FanqieBook,
  WebnovelMovementItem,
  WebnovelCategoryItem,
  WebnovelWeeklyReport,
  QimaoBook,
  ZhihuAlbum,
  ZhihuCategory,
  LlmModelItem,
  LlmModelPresetItem,
  LlmModelPresetCatalog,
  LlmModelCreatePayload,
  EvalRun,
  EvalResult,
  ModelUsageBucket,
  ModelUsageByModel,
  ModelUsageByPrompt,
  ModelUsageSummary,
};

// Core API infrastructure (request / token / error helpers) extracted to _core.ts
import {
  request,
  getAuthToken,
  setAuthToken,
  formatApiErrorDetail,
  assertUniqueIds,
  chunkArray,
  BASE_URL,
  FAVORITE_STATE_BATCH_SIZE,
} from './api/_core';
export { getAuthToken, setAuthToken, formatApiErrorDetail, FAVORITE_STATE_BATCH_SIZE };

// ─── Auth API ───

export const authApi = {
  register(data: { email: string; password: string; display_name?: string | null; verification_code: string }): Promise<AuthTokenResponse> {
    return request('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 发送邮箱验证码（注册前调用）。成功返回 204。 */
  sendCode(email: string): Promise<void> {
    return request('/auth/send-code', {
      method: 'POST',
      body: JSON.stringify({ email }),
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

  /** OAuth 登录入口 URL。前端用 window.location.href 整页跳转，
   *  后端 302 到 provider 授权页，回调后再 302 回 /oauth/callback（token 走 fragment）。 */
  oauthLoginUrl(provider: 'google' | 'github'): string {
    return `${BASE_URL}/auth/oauth/${provider}/login`;
  },

  /** 已启用的 OAuth provider 列表，前端据此渲染按钮。 */
  async oauthProviders(): Promise<{ providers: string[] }> {
    return request('/auth/oauth/providers');
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


// Domain API objects extracted to lib/api/ submodules for module size.
// Re-export for backward compat — `import { sourcesApi } from '@/lib/api'` still works.
export { sourcesApi, contentsApi, contentCategoriesApi, favoritesApi, topicsApi, analysesApi, dailyReportApi, creationApi, viralApi, apiTokensApi } from './api/_domains';
export type { SourceBatchImportItem, ApiTokenItem } from './api/_domains';
export { settingsApi, statsApi, statsJobsApi, trendsApi, feedbackApi, productFeedbackApi } from './api/_analytics';
export { weeklyDigestApi, monthlyDigestApi } from './api/_digests';
export { trendingApi } from './api/_trending';
export { motherTopicsApi } from './api/_mother-topics';
export { fanqieApi, webnovelReportsApi, qimaoApi, zhihuApi } from './api/_mother-topics';
export { modelsApi } from './api/_models';
