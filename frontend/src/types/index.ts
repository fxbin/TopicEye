import { explainRecommendation } from '@/lib/recommendation';

/**
 * TopicEye TypeScript Type Definitions
 * Aligned with backend API models (snake_case)
 */

// ─── Auth (用户) ───

export interface AuthUser {
  id: number;
  email: string;
  display_name?: string | null;
  plan: 'free' | 'paid' | string;
  role: 'admin' | 'user' | string;
  is_active: boolean;
  created_at: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: 'bearer' | string;
  expires_at: string;
  user: AuthUser;
}

// ─── Integrations (个人集成) ───

export interface IntegrationStatus {
  provider: string;
  configured: boolean;
  api_key_hint?: string | null;
  config: Record<string, unknown>;
  sync_endpoint_configured: boolean;
  install_command?: string | null;
  docs_url?: string | null;
  last_sync_at?: string | null;
  last_sync_status?: string | null;
  last_sync_error?: string | null;
}

export interface WeReadSyncResult {
  fetched: number;
  new: number;
  duplicates: number;
  message: string;
  source_name: string;
}

// ─── Plans (功能权益) ───

export interface PlanTier {
  key: 'free' | 'pro' | 'studio' | 'enterprise' | string;
  name: string;
  price_label: string;
  positioning: string;
  highlight: string;
  features: string[];
  limits: Record<string, number | string | boolean | null>;
  cta: string;
  recommended: boolean;
}

export interface PlanCatalogResponse {
  tiers: PlanTier[];
  free_area: string[];
  paid_area: string[];
  currency: string;
  source: string;
  current_plan: string;
  current_tier?: PlanTier | null;
}

// ─── Notifications (站内通知) ───

export interface NotificationItem {
  id: number;
  type: 'success' | 'error' | 'warning' | 'info' | string;
  category: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string | null;
}

export interface NotificationListResponse {
  count: number;
  notifications: NotificationItem[];
}

// ─── Source (信源) ───

export type SourceType = 'RSS' | 'RSSHub' | 'Reddit' | '网站' | 'Zhihu' | 'X' | 'TwitterRSS' | 'YouTube' | 'DouyinHot' | 'API';
export type SourceStatus = 'active' | 'syncing' | 'error' | 'disabled';

export interface Source {
  id: number;
  name: string;
  source_type: SourceType;
  url: string;
  keyword?: string | null;
  platform?: string | null;
  category: string;
  weight: number; // 1-5
  sort_order?: number;
  status: SourceStatus;
  last_sync_at: string;
  sync_error?: string | null;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface CreateSourceRequest {
  name: string;
  source_type: SourceType;
  url: string;
  keyword?: string | null;
  category: string;
  weight?: number;
  fetch_interval_minutes?: number;
  enabled?: boolean;
  sort_order?: number;
}

export interface UpdateSourceRequest {
  name?: string;
  source_type?: SourceType;
  url?: string;
  keyword?: string | null;
  category?: string;
  weight?: number;
  sort_order?: number;
  fetch_interval_minutes?: number;
  status?: SourceStatus;
  sync_error?: string | null;
  enabled?: boolean;
}

// ─── Content (内容) ───

export interface ContentItem {
  id: number;
  title: string;
  url?: string;
  source_id: number;
  source_name: string;
  source_type: SourceType;
  platform?: string | null;
  author?: string;
  published_at: string;
  crawled_at: string;
  content_hash?: string;
  summary?: string;
  raw_content?: string | null;
  cover_url?: string | null;
  category: string;
  tags?: string[];
  language?: string | null;
  status?: string;
  is_favorited?: boolean;
  created_at?: string;
  updated_at?: string;
  // Extended fields from today-picks API
  analyses?: ContentAnalysis[];
  topic_id?: number | null;
  // Legacy API field alias
  analysis?: ContentAnalysis;
}

export interface ContentMetrics {
  hotScore: number;
  creatorScore: number;
  riskScore: number;
}

export interface ArticleReaderBlock {
  type: 'heading' | 'paragraph' | 'quote' | 'list_item' | 'code';
  text: string;
  level?: number | null;
}

export interface ArticleReaderSnapshot {
  content_id: number;
  canonical_url: string;
  title: string;
  byline?: string | null;
  published_at?: string | null;
  excerpt?: string | null;
  text_content: string;
  content_blocks?: ArticleReaderBlock[];
  text_content_zh?: string | null;
  content_blocks_zh?: ArticleReaderBlock[] | null;
  reading_minutes: number;
  extraction_method: 'ingested' | 'http' | string;
  fetched_at: string;
  expires_at: string;
  cache_status: 'hit' | 'miss' | string;
}

// ─── AI Analysis (后端实际模型) ───

export interface ContentAnalysis {
  id: number;
  content_id: number;
  quality_score: number;
  hot_score: number;
  freshness_score: number;
  creator_score: number;
  viral_score: number;
  risk_score: number;
  platform_fit?: Record<string, unknown> | null;
  recommended_reason?: string | null;
  summary?: string | null;
  key_points?: string[] | null;
  audience_emotion?: string | null;
  creator_angles?: string[] | null;
  title_suggestions?: string[] | null;
  outline_suggestions?: Record<string, unknown> | null;
  xiaohongshu_plan?: Record<string, unknown> | null;
  short_video_plan?: Record<string, unknown> | null;
  risk_notes?: Record<string, unknown> | null;
  // Curation fields
  curation_score?: number | null;
  tags?: string[] | null;
  recommendation?: string | null;
  info_density?: number | null;
  actionability?: number | null;
  source_weight?: number | null;
  // Round-2 enrichment fields
  enrichment_status?: string | null;
  enrichment?: Record<string, unknown> | null;
  // Scoring engine fields (from today-picks API)
  adjusted_curation_score?: number | null;
  score_breakdown?: ScoreBreakdown | null;
  created_at: string;
}

// ─── Score Breakdown ───

export interface ScoreBreakdown {
  content_id: number;
  base_score: number;
  source_bonus: number;
  quality_factor?: number;
  risk_factor?: number;
  time_decay: number;
  diversity_factor: number;
  final_score: number;
  dimension_scores: Record<string, number>;
  selected: boolean;
}

// ─── Recommend Level ───

export type RecommendLevel = '强烈建议写' | '值得观察' | '适合深挖' | '适合蹭热点' | '不建议追' | '信号不足';

export function getRecommendLevel(analysis: ContentAnalysis): RecommendLevel {
  return explainRecommendation(analysis).level;
}

// ─── Topic (选题) ───

export interface Topic {
  id: number;
  title: string;
  source: string;
  sourceType: SourceType;
  publishedAt: string;
  categories: string[];
  hotScore: number;
  creatorScore: number;
  riskScore: number;
  recommendLevel: RecommendLevel;
  reason: string;
  platforms: string[];
  aiSummary: string;
  angles: string[];
  platformFit: PlatformFit[];
  riskNotes: string[];
  similarArticles: SimilarArticle[];
}

export interface PlatformFit {
  platform: string;
  suggestion: string;
}

export interface SimilarArticle {
  title: string;
  source: string;
  metrics: string;
}

// Today-picks API response topic shape
export interface TopicInfo {
  id: number;
  name: string;
  summary: string | null;
  keywords: string[] | null;
  best_score: number;
}

// ─── Daily Report ───

export interface DailyReport {
  date: string;
  weekday: string;
  topicCount: number;
  isToday: boolean;
  overview: string;
  keywords: string[];
  trends: DailyTrend[];
  topPicks: DailyTopPick[];
  platformTips: Record<string, string[]>;
  takeaway: string;
}

export interface DailyTrend {
  title: string;
  desc: string;
  color: string;
}

export interface DailyTopPick {
  title: string;
  reason: string;
  score: number;
  platforms: string[];
}

// ─── API Response Wrappers ───

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ─── Favorites (通用收藏) ───

export type FavoriteTargetType = 'content' | 'book' | 'source' | 'trend' | 'author' | 'topic_group';
export type FavoriteStatus = 'inbox' | 'researching' | 'drafting' | 'archived';

export interface FavoriteItem {
  id: number;
  user_id: number;
  target_type: FavoriteTargetType;
  target_id?: number | null;
  target_key: string;
  title: string;
  url?: string | null;
  cover_url?: string | null;
  source_name?: string | null;
  collection_id?: number | null;
  tags?: unknown;
  note?: string | null;
  status: FavoriteStatus;
  position: number;
  snapshot?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface SyncResult {
  fetched: number;
  new: number;
  duplicates: number;
}

// ─── Filter Params ───

export interface TopicFilterParams {
  category?: string;
  recommendLevel?: string;
  page?: number;
  pageSize?: number;
}

export interface ContentFilterParams {
  sourceId?: number;
  source_id?: number;
  category?: string;
  page?: number;
  page_size?: number;
  pageSize?: number;
  hours?: number;
  include_trend_sources?: boolean;
  source_type?: string;
  keyword?: string;
  [key: string]: unknown; // allow any extra params for URLSearchParams
}

// ─── Weekly Digest (周刊) ───

export interface WeeklyDigest {
  id: number;
  week_key: string;
  week_label: string;
  week_start: string;
  week_end: string;
  overview: string | null;
  takeaway: string | null;
  keywords: string[] | null;
  trends: WeeklyDigestTrend[] | null;
  top_picks: WeeklyDigestTopPick[] | null;
  category_summary: Record<string, { count: number; avg_score: number; top_title: string }> | null;
  platform_tips: Record<string, string[]> | null;
  topic_clusters: WeeklyDigestTopicCluster[] | null;
  action_items: WeeklyDigestActionItem[] | null;
  content_count: number;
  analyzed_count: number;
  source_count: number;
  category_count: number;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface WeeklyDigestTrend {
  title: string;
  desc: string;
  color: string;
  momentum?: string;
}

export interface WeeklyDigestTopPick {
  rank: number;
  title: string;
  source: string;
  category: string;
  reason: string;
  score: number;
  platforms: string[];
}

export interface WeeklyDigestTopicCluster {
  name: string;
  count: number;
  heat: number;
  representative_title: string;
}

export interface WeeklyDigestActionItem {
  title: string;
  angle: string;
  difficulty: string;
  platform: string;
}

export interface WeeklyDigestWeekSummary {
  week_key: string;
  week_label: string;
  takeaway: string | null;
  status: string;
}

export interface WeeklyDigestListResponse {
  items: WeeklyDigest[];
  total: number;
}

export interface WeeklyDigestWeeksResponse {
  weeks: WeeklyDigestWeekSummary[];
}

// ─── Monthly Digest (月刊) ───

export interface MonthlyDigest {
  id: number;
  month_key: string;
  month_label: string;
  month_start: string;
  month_end: string;
  overview: string | null;
  takeaway: string | null;
  keywords: string[] | null;
  trends: WeeklyDigestTrend[] | null;
  top_picks: WeeklyDigestTopPick[] | null;
  category_summary: Record<string, { count: number; avg_score: number; top_title: string }> | null;
  platform_tips: Record<string, string[]> | null;
  topic_clusters: WeeklyDigestTopicCluster[] | null;
  action_items: WeeklyDigestActionItem[] | null;
  content_count: number;
  analyzed_count: number;
  source_count: number;
  category_count: number;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface MonthlyDigestMonthSummary {
  month_key: string;
  month_label: string;
  takeaway: string | null;
  status: string;
}

export interface MonthlyDigestListResponse {
  items: MonthlyDigest[];
  total: number;
}

export interface MonthlyDigestMonthsResponse {
  months: MonthlyDigestMonthSummary[];
}
