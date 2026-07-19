/**
 * 趋势雷达与跨平台聚类、母题类型。
 *
 * 从 lib/api.ts 拆出，通过 lib/api re-export 保持向后兼容。
 */

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
  owner_user_id: number | null;
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