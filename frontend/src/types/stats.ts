/**
 * Stats / Dashboard / Job execution stats 类型。
 *
 * 从 lib/api.ts 拆出，与 @/lib/api 的 statsApi / statsJobsApi / settingsApi 配合使用。
 * 也通过 types/index.ts re-export，保持 `import { StatsDashboard } from '@/types'` 兼容。
 */

// ─── Settings (RSSHub 实例) ───

export interface RSSHubInstance {
  url: string;
  enabled: boolean;
  priority: number;
  note: string;
}

// ─── Stats Dashboard ───

export interface StatsOverview {
  total: number;
  analyzed: number;
  curated: number;
  today_new: number;
}

export interface StatsSourceItem {
  source_name: string;
  source_type: string;
  content_count: number;
  curated_count: number;
  curation_rate: number;
}

export interface StatsCategoryItem {
  category: string;
  content_count: number;
  avg_score: number;
}

export interface StatsTrendItem {
  date: string;
  content_count: number;
  curated_count: number;
  analyzed_count: number;
}

export interface StatsNovelPlatform {
  name: string;
  table: string;
  count: number;
  last_sync: string | null;
}

export interface StatsDashboard {
  overview: StatsOverview;
  sources: StatsSourceItem[];
  categories: StatsCategoryItem[];
  trend: StatsTrendItem[];
  platforms: StatsNovelPlatform[];
  kpi: { total_crawled: number; total_curated: number; avg_curation: number; active_sources: number };
  source_breakdown: Array<{ source_name: string; source_type: string; content_count: number; curated_count: number; avg_score: number }>;
  daily_trend: Array<{ date: string; content_count: number; curated_count: number; avg_curation: number }>;
}

// ─── Job execution stats ───

export interface JobStatsByStatus {
  status: string;
  count: number;
}

export interface JobStatsByJobKey {
  job_key: string;
  runs: number;
  success_count: number;
  success_rate: number;
  avg_duration_ms: number;
  last_status: string | null;
  last_run_at: string | null;
  last_duration_ms: number | null;
  last_error: string | null;
}

export interface JobStatsRecentFailure {
  job_key: string;
  status: string;
  started_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
}

export interface JobStatsResponse {
  period: { days: number; start: string; end: string };
  totals: {
    total_runs: number;
    success_count: number;
    failed_count: number;
    timeout_count: number;
    skipped_count: number;
    running_count: number;
    success_rate: number;
    avg_duration_ms: number;
    max_duration_ms: number;
  };
  by_status: JobStatsByStatus[];
  by_job_key: JobStatsByJobKey[];
  recent_failures: JobStatsRecentFailure[];
}