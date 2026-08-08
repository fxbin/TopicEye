/**
 * _domains barrel — re-exports from domain-specific sub-modules.
 *
 * 原始 1019 行文件已按业务域拆分为 4 个子模块：
 * - _sources.ts：信源 API + SourceBatchImportItem
 * - _contents.ts：内容 API + 分类 API + 低粉爆文 API
 * - _daily-reports.ts：日报 API + 创作 API + WebhookDeliveryLogItem
 * - _admin-api.ts：收藏/选题/分析/Token/证据/内容事件 API + 类型
 *
 * 本文件仅做 re-export，保持 api.ts 和其他 importer 的 import 路径不变。
 */

export { sourcesApi } from './_sources';
export type { SourceBatchImportItem } from './_sources';

export { contentsApi, contentCategoriesApi, viralApi } from './_contents';

export { dailyReportApi, creationApi } from './_daily-reports';
export type { WebhookDeliveryLogItem } from './_daily-reports';

export { favoritesApi, topicsApi, analysesApi, apiTokensApi, evidenceApi, contentEventsAdminApi } from './_admin-api';
export type {
  ApiTokenItem,
  EvidenceStats,
  EvidenceEffectStats,
  ContentEventRelation,
  ContentEventReviewStatus,
  ContentEventNormalizationMode,
  ContentEventNormalizationScope,
  ContentEventReviewItem,
  ContentEventReviewListResponse,
  ContentEventMutationResponse,
  ContentEventNormalizeRequest,
  ContentEventNormalizeResponse,
} from './_admin-api';
