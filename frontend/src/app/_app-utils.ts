/**
 * Home page 静态配置与工具函数。
 *
 * 从 app/page.tsx 抽出：
 * - TIME_RANGE_HOURS    时间范围筛选（24h/48h/7d/全部）
 * - RECOMMEND_FILTERS   推荐等级筛选（全部/强烈建议写/值得观察/适合深挖/适合蹭热点/信号不足）
 * - getContentTime      取条目最早可用时间字段
 * - normalizeTags       兼容 array / 逗号字符串 / null 三种 tags 格式
 * - getItemTags         合并 content.tags + analysis.tags + analyses[0].tags（去重）
 * - formatShanghaiToday 上海时区今日日期
 *
 * 子组件 _components.tsx 依赖本模块，page.tsx 通过 re-export 保持外部 import 路径不变。
 */

import type { ContentItem, RecommendLevel } from '@/types';

export const TIME_RANGE_HOURS: Record<string, number | undefined> = {
  '24h': 24,
  '48h': 48,
  '7d': 168,
  '全部': undefined,
};

export const RECOMMEND_FILTERS: Array<RecommendLevel | '全部'> = [
  '全部',
  '强烈建议写',
  '值得观察',
  '适合深挖',
  '适合蹭热点',
  '信号不足',
];

export function getContentTime(item: ContentItem): string {
  return item.published_at || item.crawled_at || item.created_at || '';
}

export function normalizeTags(rawTags: unknown): string[] {
  if (Array.isArray(rawTags)) {
    return rawTags.map((tag) => String(tag).trim()).filter(Boolean);
  }
  if (typeof rawTags === 'string' && rawTags.trim()) {
    return rawTags.split(',').map((tag) => tag.trim()).filter(Boolean);
  }
  return [];
}

export function getItemTags(item: ContentItem): string[] {
  return Array.from(
    new Set([
      ...normalizeTags(item.tags),
      ...normalizeTags(item.analysis?.tags),
      ...normalizeTags(item.analyses?.[0]?.tags),
    ]),
  );
}

export function formatShanghaiToday(): string {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).formatToParts(new Date());
  const get = (type: string) => parts.find((part) => part.type === type)?.value || '';
  return `${get('year')} 年 ${get('month')} 月 ${get('day')} 日`;
}