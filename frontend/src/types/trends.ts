import type { EvidenceMark } from './index';

/**
 * 趋势（topic 曲线 + 关键词云）类型。
 *
 * 从 lib/api.ts 拆出，通过 lib/api re-export 保持向后兼容。
 */

export interface TrendPoint {
  date: string;
  topic_id: number;
  topic_name: string;
  content_count: number;
  avg_score: number;
  max_score: number;
  pick_count: number;
  top_items: { title: string; url: string; score: number }[] | null;
  /** Frozen snapshot metadata. Absent only for legacy responses. */
  snapshot_id?: number | null;
  provenance_status?: TrendProvenanceStatus;
  generated_at?: string | null;
  calculation_version?: string | null;
}

export interface TrendKeywordItem {
  keyword: string;
  count: number;
  /** Whether this aggregate can be traced back to complete member records. */
  traceability?: TrendProvenanceStatus;
}

export type TrendProvenanceStatus = 'complete' | 'sample_only' | 'unavailable' | string;

export type TrendEvidenceFilter = 'all' | 'selected' | 'evidenced';

export type TrendEvidenceRequest =
  | { kind: 'topic'; topicId: number; topicName: string; date: string }
  | { kind: 'keyword'; keyword: string; days: number };

export interface TrendEvidenceScope {
  kind: 'topic' | 'keyword' | string;
  key: string;
  label: string;
  start_date: string;
  end_date: string;
}

export interface TrendEvidenceSummary {
  content_count: number;
  source_count: number;
  selected_count: number;
  evidenced_count: number;
  provenance_status: TrendProvenanceStatus;
}

export interface TrendEvidenceCalculation {
  version: string | null;
  generated_at: string | null;
  window_start: string | null;
  window_end: string | null;
  event_members_excluded: boolean;
}

export interface TrendEvidenceDailyCount {
  date: string;
  count: number;
}

export interface TrendEvidenceItem {
  content_id: number | null;
  title: string;
  url: string | null;
  source_id: number | null;
  source_name: string | null;
  source_type: string | null;
  platform: string | null;
  published_at: string | null;
  crawled_at: string | null;
  time_basis: 'published_at' | 'crawled_at' | string;
  score: number | null;
  selected: boolean;
  evidence_mark: EvidenceMark | null;
}

export interface TrendEvidenceResponse {
  scope: TrendEvidenceScope;
  summary: TrendEvidenceSummary;
  calculation: TrendEvidenceCalculation;
  daily_counts: TrendEvidenceDailyCount[];
  items: TrendEvidenceItem[];
  page: number;
  page_size: number;
  total: number;
  /** Explains degraded legacy traceability without hiding the available samples. */
  message?: string | null;
}
