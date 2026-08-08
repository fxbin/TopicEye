/**
 * 微信读书书架页共享类型、常量与纯工具函数。
 *
 * 从 _shared.tsx 拆出，不含 React 组件。
 */

import type { ContentItem } from '@/types';

export const SHELF_PAGE_SIZE = 200; // 书架视图一次拉满，客户端排序/分组

// ── 从 summary 解析 WeRead 结构化数据 ──

export interface WeReadMeta {
  noteCount: number;
  reviewCount: number;
  readingProgress: number; // 0-100
}

export function parseWeReadMeta(item: ContentItem): WeReadMeta {
  const summary = item.summary || '';
  const raw = item.raw_content || '';
  const text = `${summary}\n${raw}`;
  const noteMatch = text.match(/(\d+)\s*条划线/);
  const reviewMatch = text.match(/(\d+)\s*条想法/);
  const progressMatch = text.match(/阅读进度\s*(\d+)%/);
  return {
    noteCount: noteMatch ? parseInt(noteMatch[1], 10) : 0,
    reviewCount: reviewMatch ? parseInt(reviewMatch[1], 10) : 0,
    readingProgress: progressMatch ? parseInt(progressMatch[1], 10) : 0,
  };
}

// ── 排序 & 分组类型 ──

export type SortKey = 'published_at' | 'title' | 'noteCount' | 'reviewCount' | 'readingProgress';
export type SortOrder = 'asc' | 'desc';
export type GroupKey = 'none' | 'author' | 'status' | 'weread_category';

export const SORT_OPTIONS: Array<{ value: SortKey; label: string }> = [
  { value: 'published_at', label: '最近笔记' },
  { value: 'title', label: '书名' },
  { value: 'noteCount', label: '划线数' },
  { value: 'reviewCount', label: '想法数' },
  { value: 'readingProgress', label: '阅读进度' },
];

export const GROUP_OPTIONS: Array<{ value: GroupKey; label: string }> = [
  { value: 'none', label: '不分组' },
  { value: 'author', label: '按作者' },
  { value: 'status', label: '按阅读状态' },
  { value: 'weread_category', label: '微信读书分类' },
];

export function getReadingStatus(progress: number): '未读' | '在读' | '已读' {
  if (progress >= 90) return '已读';
  if (progress > 0) return '在读';
  return '未读';
}

// ── 微信读书网页版跳转 URL ──

export const WEREAD_FALLBACK_URL = 'https://weread.qq.com/r/weread-skills';

/** 构造微信读书网页版搜索 URL，用于书架中没有直接 deepLink 的书 */
export function wereadSearchUrl(title: string): string {
  return `https://weread.qq.com/#search/${encodeURIComponent(title)}`;
}

/** 获取书架书籍的微信读书跳转 URL：有真实 URL 用 URL，否则用搜索 URL */
export function wereadBookUrl(item: ContentItem): string {
  if (item.url && item.url !== WEREAD_FALLBACK_URL) {
    return item.url;
  }
  return wereadSearchUrl(item.title);
}

/** 检测是否为暂停阅读：进度 < 50% 且 30 天无笔记活动 */
export function isPausedReading(meta: WeReadMeta, publishedAt: string | null): boolean {
  if (meta.readingProgress >= 50) return false;
  if (!publishedAt) return false;
  const date = new Date(publishedAt);
  if (Number.isNaN(date.getTime())) return false;
  const daysSince = (Date.now() - date.getTime()) / (1000 * 60 * 60 * 24);
  return daysSince >= 30;
}
