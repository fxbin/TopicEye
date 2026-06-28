/**
 * 内容分类与评分流（scoring flow）相关类型。
 *
 * 从 lib/api.ts 拆出，通过 lib/api re-export 保持向后兼容。
 */

export interface ContentCategoryItem {
  id: number;
  name: string;
  description?: string | null;
  keywords: string[];
  is_auto_created: boolean;
  content_count: number;
}

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

/** Topic group response from topicsApi.list（后端返回 {items, total}） */
export interface TopicGroupResponse {
  id: number;
  name: string;
  summary: string | null;
  keywords: string[] | null;
  content_count: number;
  best_score: number;
}