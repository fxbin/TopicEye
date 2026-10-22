/**
 * 日报页面共享类型、常量与工具函数。
 *
 * 从 page.tsx 提取，保持行为完全等价。
 */

// ── Types ────────────────────────────────────────────────────────────

export interface DailyReportData {
  id: number;
  report_date: string;
  weekday: string;
  edition?: string;
  generated_at?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  cutoff_at?: string | null;
  source_scope?: string;
  source_item_ids?: number[] | null;
  updated_at?: string | null;
  overview: string | null;
  takeaway: string | null;
  keywords: string[] | null;
  trends: Array<{ title: string; desc: string; color: string; momentum?: string }> | null;
  top_picks: Array<{
    title: string;
    reason: string;
    score: number;
    platforms: string[];
    source_url?: string;
    angles?: string[];
    pitfall?: string;
    lifecycle?: string;
    time_window?: string;
    category?: string;
    source_idx?: number;
    source_title?: string;
    source_title_zh?: string;
    editorial_title?: string;
    tier?: 'feature' | 'brief';
    content_id?: number;
  }> | null;
  platform_tips: Record<string, string[]> | null;
  topic_count: number;
  content_count: number;
  analyzed_count: number;
  status: string;
}

export interface DateSummary {
  report_date: string;
  weekday: string;
  takeaway: string | null;
  status: string;
  edition?: string;
  generated_at?: string | null;
  cutoff_at?: string | null;
}

export interface CalendarDay {
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
}

export type MarkAction = 'write' | 'watch' | 'skip';

// ── Pick type used by extracted components ───────────────────────────

export interface DailyPick {
  title: string;
  reason: string;
  score?: number;
  platforms?: string[];
  source_url?: string;
  angles?: string[];
  pitfall?: string;
  lifecycle?: string;
  time_window?: string;
  category?: string;
  source_idx?: number;
  source_title?: string;
  source_title_zh?: string;
  editorial_title?: string;
  tier?: 'feature' | 'brief';
  content_id?: number;
}

// ── Constants ────────────────────────────────────────────────────────

// #132 改名让位：种属词族「今日情报/每周情报…」住在 @/lib/edition-naming 的
// EDITION_LABELS；本表是日报快照的生命周期轴，语义不同，勿混用。
export const SNAPSHOT_EDITION_LABELS: Record<string, string> = {
  noon: '午间快照',
  evening: '晚间快照',
  snapshot: '实时快照',
  manual: '手动快照',
  final: '完整复盘',
  legacy: '历史情报',
};

export const LIFECYCLE_META: Record<string, { label: string; color: string; bg: string }> = {
  '上升期': { label: '↑ 上升期', color: 'text-teal-text', bg: 'bg-teal-light' },
  '见顶': { label: '→ 见顶', color: 'text-amber-800', bg: 'bg-amber-light' },
  '退潮': { label: '↓ 退潮', color: 'text-gray-500', bg: 'bg-gray-100' },
};

export const CATEGORY_ORDER = ['模型发布', '产品更新', '行业动态', '技巧观点', '科研论文', '开源项目'];

export const CATEGORY_EN: Record<string, string> = {
  '模型发布': 'Model Releases',
  '产品更新': 'Product Updates',
  '行业动态': 'Industry',
  '技巧观点': 'Tips & Takes',
  '科研论文': 'Research',
  '开源项目': 'Open Source',
};

// ── Utility functions ────────────────────────────────────────────────

export function localDateString(date = new Date()) {
  return date.toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' });
}

export function formatDateTime(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16).replace('T', ' ');
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function parseJson(val: unknown) {
  if (typeof val === 'string') {
    try {
      return JSON.parse(val);
    } catch {
      return null;
    }
  }
  return val;
}

/**
 * 选题稳定键：优先 source_title（原文标题，跨版本稳定），无则回退 title。
 */
export function pickKey(pick: { source_title?: string; title?: string }): string {
  return pick.source_title || pick.title || '';
}

/**
 * 判断原文标题是否主要为英文（含 CJK 字符少、Latin 字母多）。
 */
export function isEnglishTitle(title?: string): boolean {
  if (!title) return false;
  const cjk = (title.match(/[\u4e00-\u9fff]/g) || []).length;
  const latin = (title.match(/[a-zA-Z]/g) || []).length;
  return latin > 0 && cjk < latin * 0.3;
}

/**
 * 返回展示用的原文标题：默认中文翻译，可切换英文原文。
 */
export function displaySourceTitle(pick: { source_title?: string; source_title_zh?: string }, showOriginal: boolean): string {
  if (showOriginal) return pick.source_title || '';
  return pick.source_title_zh || pick.source_title || '';
}

export function marksMapFromResp(marks: Array<{ pick_title: string; action: string }>): Record<string, MarkAction> {
  const map: Record<string, MarkAction> = {};
  for (const m of marks) {
    map[m.pick_title] = m.action as MarkAction;
  }
  return map;
}

/**
 * 按 category 分组选题，按 CATEGORY_ORDER 排序。
 */
export function groupByCategory(picks: DailyPick[], tierFilter: 'feature' | 'brief'): Array<[string, DailyPick[]]> {
  const groups: Record<string, DailyPick[]> = {};
  for (const pick of picks) {
    if (tierFilter === 'feature') {
      if (pick.tier && pick.tier !== 'feature') continue;
    } else {
      if (pick.tier !== 'brief') continue;
    }
    const cat = pick.category || '精选选题';
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(pick);
  }
  return Object.entries(groups).sort(([a], [b]) => {
    const ia = CATEGORY_ORDER.indexOf(a);
    const ib = CATEGORY_ORDER.indexOf(b);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
}

/** 日期目录的 API 按新到旧返回；排序后取最近几期，排除当前期与未完成期。 */
export function recentReportDates(dates: DateSummary[], currentDate?: string, limit = 5) {
  return dates.filter((d) => d.report_date !== currentDate && d.status === 'DONE')
    .sort((a, b) => b.report_date.localeCompare(a.report_date)).slice(0, limit);
}

/** All daily entry points carry the same chosen topic into the creation page. */
export function creationPlanHref(pick: { title?: string; source_title?: string; source_title_zh?: string; source_url?: string }) {
  const params = new URLSearchParams({ title: pick.source_title_zh || pick.source_title || pick.title || '' });
  if (pick.source_url) params.set('url', pick.source_url);
  return `/plan?${params}`;
}

/** API failures carry a status code; server wording is not an error contract. */
export function reportLoadError(error: unknown) {
  if (error instanceof Error) {
    return (error as Error & { status?: number }).status === 404 ? '该日期暂无情报' : error.message;
  }
  return '加载失败';
}

/** Shift an ISO report date without passing through the browser's timezone. */
export function shiftReportDate(isoDate: string, days: number) {
  const date = new Date(`${isoDate}T00:00:00Z`);
  if (!Number.isFinite(date.getTime())) return isoDate;
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
