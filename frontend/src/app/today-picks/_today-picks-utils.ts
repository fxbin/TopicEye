/**
 * Today picks page 静态配置与工具函数（无 React 依赖）。
 *
 * 从 app/today-picks/page.tsx 抽出：
 * - CATEGORIES / RECOMMEND_LEVELS（从 design-tokens 复用）
 * - LEVEL_CONFIG（从 design-tokens 复用 LEVEL_CONFIG_CLASSES）
 * - TIME_RANGES / DEFAULT_TIME_RANGE / INITIAL_PICK_LIMIT / PICK_LOAD_STEP
 * - normalizeTimeRange
 * - getAnalysis / scoreOf / tagsOf（纯函数工具）
 */

import { CATEGORIES, LEVEL_CONFIG_CLASSES } from '@/lib/design-tokens';
import { getRecommendLevelLabel } from '@/lib/utils';
import type { ContentAnalysis, ContentItem } from '@/types';

// re-export 让调用方 import 路径不变
export { CATEGORIES };

export const RECOMMEND_LEVELS = ['强烈建议写', '值得观察', '适合深挖', '适合蹭热点', '不建议追', '信号不足'] as const;

// 复用 design-tokens 的 class 格式版，字段名 bg/color/border/dot
// 注：page.tsx 原用 cfg.text，迁移后改用 cfg.color（与 LEVEL_CONFIG_CLASSES 字段名一致）
export const LEVEL_CONFIG = LEVEL_CONFIG_CLASSES;

export const TIME_RANGES = [
  { value: '24h', label: '24h' },
  { value: '48h', label: '48h' },
  { value: '7d', label: '7d' },
] as const;

export const DEFAULT_TIME_RANGE = '24h';
export const INITIAL_PICK_LIMIT = 40;
export const PICK_LOAD_STEP = 40;

export function normalizeTimeRange(value: string | null) {
  return TIME_RANGES.some((range) => range.value === value) ? value! : DEFAULT_TIME_RANGE;
}

// ── 纯函数工具 ──────────────────────────────────────────────────────

export function getAnalysis(item: ContentItem): ContentAnalysis | undefined {
  return item.analysis || item.analyses?.[0];
}

export function scoreOf(item: ContentItem): number {
  const analysis = getAnalysis(item);
  return analysis?.adjusted_curation_score || analysis?.curation_score || 0;
}

export function tagsOf(analysis?: ContentAnalysis | null): string[] {
  const rawTags = analysis?.tags as string | string[] | null | undefined;
  if (Array.isArray(rawTags)) return rawTags;
  if (typeof rawTags === 'string' && rawTags) return rawTags.split(',').map((tag) => tag.trim()).filter(Boolean);
  return [];
}

export { getRecommendLevelLabel };
