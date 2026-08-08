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

export const EDITION_LABELS: Record<string, string> = {
  noon: '午间快照',
  evening: '晚间快照',
  snapshot: '实时快照',
  manual: '手动快照',
  final: '完整复盘',
  legacy: '历史日报',
};

export const CALENDAR_STATUS_META: Record<string, { label: string; text: string; bg: string; border: string; active: string }> = {
  DONE: { label: '已完成', text: 'text-teal', bg: 'bg-teal-light', border: 'border-teal-border', active: 'bg-teal text-white border-teal' },
  ERROR: { label: '失败', text: 'text-red', bg: 'bg-red-light', border: 'border-red-light', active: 'bg-red text-white border-red' },
  MISSING: { label: '缺失', text: 'text-amber', bg: 'bg-amber-light', border: 'border-amber-border', active: 'bg-amber text-white border-amber' },
  GENERATING: { label: '生成中', text: 'text-primary', bg: 'bg-primary-light', border: 'border-primary-border', active: 'bg-primary text-white border-primary' },
};

export const LIFECYCLE_META: Record<string, { label: string; color: string; bg: string }> = {
  '上升期': { label: '↑ 上升期', color: 'text-teal', bg: 'bg-teal-light' },
  '见顶': { label: '→ 见顶', color: 'text-amber', bg: 'bg-amber-light' },
  '退潮': { label: '↓ 退潮', color: 'text-gray-400', bg: 'bg-gray-100' },
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
  return date.toLocaleDateString('en-CA');
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

export function formatTimeOnly(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(11, 16);
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
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
