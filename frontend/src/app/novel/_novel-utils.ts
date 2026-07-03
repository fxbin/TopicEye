/**
 * Novel page 静态配置、类型与工具函数。
 *
 * 从 app/novel/page.tsx 抽出：
 * - 3 个类型：Platform / BookItem / ViewMode
 * - BookFavoriteMeta interface
 * - 12 个配置常量：PLATFORM_META / GROUP_LABELS / RANK_TYPE_LABELS /
 *   QIMAO_RANK_LABELS / ISHUGUI_RANK_LABELS / ISHUGUI_SHELF_TO_RANK /
 *   HEIYAN_SORT_STYLE / HEIYAN_SORT_FALLBACK / HEIYAN_HOME_SHELF_LABELS /
 *   HEIYAN_TYPE_STYLE / QIMAO_CHANNEL_LABELS / ZHIHU_SORT_LABELS / ZHIHU_SUBCATS
 * - 11 个工具函数：formatCount / getItemTitle / getItemAuthor / getItemAbstract /
 *   getItemCover / getItemUrl / getPositionChange / getBookStableId /
 *   getBookFavoriteMeta / chipStyle / formatDate
 *
 * 子组件 _components.tsx 和主页面 page.tsx 都依赖本模块。
 */

import type React from 'react';
import type { FanqieBook, QimaoBook, ZhihuAlbum } from '@/lib/api';

export type Platform = 'fanqie' | 'qimao' | 'zhihu' | 'heiyan' | 'ishugui';
export type BookItem = FanqieBook | QimaoBook | ZhihuAlbum;
export type ViewMode = 'rankings' | 'weekly';

export interface BookFavoriteMeta {
  target_key: string;
  title: string;
  url: string | null;
  cover_url: string | null;
  source_name: string;
  snapshot: Record<string, unknown>;
}

export const PLATFORM_META: Record<Platform, { label: string; subtitle: string; color: string; bg: string }> = {
  fanqie: { label: '番茄小说', subtitle: '免费网文热榜', color: '#DC2626', bg: '#FEF2F2' },
  qimao: { label: '七猫小说', subtitle: '付费与免费混合榜', color: '#2563EB', bg: '#EFF6FF' },
  zhihu: { label: '知乎盐选', subtitle: '故事与付费内容', color: '#0F766E', bg: '#ECFDF5' },
  heiyan: { label: '黑岩书城', subtitle: '掌文品读公开 CDN', color: '#A855F7', bg: '#F5F0FF' },
  ishugui: { label: '点众阅读', subtitle: 'Next.js 公开榜单', color: '#0EA5E9', bg: '#EBF8FF' },
};

export const GROUP_LABELS = {
  male: { label: '男频', color: '#2563EB', bg: '#EFF6FF' },
  female: { label: '女频', color: '#E11D48', bg: '#FFF1F2' },
} as const;

export const RANK_TYPE_LABELS = {
  reading: { label: '阅读榜', color: '#059669', bg: '#ECFDF5' },
  new: { label: '新书榜', color: '#7C3AED', bg: '#F5F3FF' },
} as const;

export const QIMAO_RANK_LABELS = {
  hot: { label: '大热', color: '#DC2626', bg: '#FEF2F2' },
  new: { label: '新书', color: '#7C3AED', bg: '#F5F3FF' },
  over: { label: '完结', color: '#D97706', bg: '#FFFBEB' },
  collect: { label: '收藏', color: '#2563EB', bg: '#EFF6FF' },
  update: { label: '更新', color: '#059669', bg: '#ECFDF5' },
} as const;

export const ISHUGUI_RANK_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  bestselling:  { label: '畅销榜', color: '#DC2626', bg: '#FEF2F2' },
  finished:     { label: '完本榜', color: '#D97706', bg: '#FFFBEB' },
  newest:       { label: '新书榜', color: '#7C3AED', bg: '#F5F3FF' },
  hot_read:     { label: '热读榜', color: '#059669', bg: '#ECFDF5' },
  top_rated:    { label: '好评榜', color: '#2563EB', bg: '#EFF6FF' },
  classic:      { label: '经典榜', color: '#4B5563', bg: '#F3F4F6' },
};

export const ISHUGUI_SHELF_TO_RANK: Record<string, string> = {
  '男生小说畅销榜': 'bestselling', '男生小说完本榜': 'finished',
  '男生小说新书榜': 'newest', '男生小说热读榜': 'hot_read',
  '男生小说好评榜': 'top_rated', '男生小说经典榜': 'classic',
  '女生小说畅销榜': 'bestselling', '女生小说完本榜': 'finished',
  '女生小说新书榜': 'newest', '女生小说热读榜': 'hot_read',
  '女生小说好评榜': 'top_rated', '女生小说经典榜': 'classic',
};

export const HEIYAN_SORT_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  '现言': { label: '现言', color: '#9333EA', bg: '#F3E8FF' },
  '古言': { label: '古言', color: '#B45309', bg: '#FEF3C7' },
  '世情': { label: '世情', color: '#0F766E', bg: '#CCFBF1' },
  '现实': { label: '现实', color: '#1F2937', bg: '#E5E7EB' },
  '豪门': { label: '豪门', color: '#9F1239', bg: '#FFE4E6' },
  '重生': { label: '重生', color: '#7C3AED', bg: '#EDE9FE' },
  '穿越': { label: '穿越', color: '#0369A1', bg: '#E0F2FE' },
  '其他': { label: '其他', color: '#6B7280', bg: '#F3F4F6' },
};
export const HEIYAN_SORT_FALLBACK = HEIYAN_SORT_STYLE['其他'];

export const HEIYAN_HOME_SHELF_LABELS: Record<string, string> = {
  '书城轮播图': '编辑精选',
};

export const HEIYAN_TYPE_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  '1': { label: '短篇', color: '#0F766E', bg: '#CCFBF1' },
  '3': { label: '长篇', color: '#9F1239', bg: '#FFE4E6' },
};

export const QIMAO_CHANNEL_LABELS = {
  boy: { label: '男频', color: '#2563EB', bg: '#EFF6FF' },
  girl: { label: '女频', color: '#E11D48', bg: '#FFF1F2' },
} as const;

export const ZHIHU_SORT_LABELS = {
  hottest: { label: '热门', color: '#DC2626', bg: '#FEF2F2' },
  newest: { label: '最新', color: '#7C3AED', bg: '#F5F3FF' },
  monthly_hottest: { label: '月热', color: '#D97706', bg: '#FFFBEB' },
} as const;

export const ZHIHU_SUBCATS = [
  { key: '', label: '全部' }, { key: '爱情', label: '爱情' },
  { key: '科幻', label: '科幻' }, { key: '历史', label: '历史' },
  { key: '漫画', label: '漫画' }, { key: '脑洞', label: '脑洞' },
  { key: '奇闻', label: '奇闻' }, { key: '亲历', label: '亲历' },
  { key: '校园', label: '校园' }, { key: '悬疑', label: '悬疑' },
];

export function formatCount(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '-';
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (Number.isNaN(n)) return String(v);
  if (n >= 100000000) return `${(n / 100000000).toFixed(1)}亿`;
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return String(n);
}

export function getItemTitle(item: BookItem): string {
  if ('book_name' in item) return item.book_name;
  return item.title;
}

export function getItemAuthor(item: BookItem): string {
  return item.author || '未知作者';
}

export function getItemAbstract(item: BookItem): string {
  return (item.abstract || '').replace(/\n/g, ' ');
}

export function getItemCover(item: BookItem): string | null {
  if ('thumb_url' in item) return item.thumb_url;
  return item.thumb_uri;
}

export function getItemUrl(item: BookItem): string | null {
  if ('url' in item && item.url) return item.url;
  return null;
}

export function getPositionChange(item: BookItem): number | null {
  if ('rank_pos_diff' in item && typeof item.rank_pos_diff === 'number') return item.rank_pos_diff;
  if ('index_change' in item && typeof item.index_change === 'number') return item.index_change;
  return null;
}

export function getBookStableId(item: BookItem, platform: Platform): string {
  if (platform === 'zhihu' && 'business_id' in item) return item.business_id;
  return 'book_id' in item ? item.book_id : item.business_id;
}

export function getBookFavoriteMeta(item: BookItem, platform: Platform, rankTab: string): BookFavoriteMeta {
  const stableId = getBookStableId(item, platform);
  const categoryText = 'category1_name' in item
    ? [item.category1_name, item.category2_name].filter(Boolean).join(' · ')
    : '';
  return {
    target_key: `${platform}:${stableId}`,
    title: getItemTitle(item),
    url: getItemUrl(item),
    cover_url: getItemCover(item),
    source_name: PLATFORM_META[platform].label,
    snapshot: {
      platform, platform_label: PLATFORM_META[platform].label,
      author: getItemAuthor(item), category: categoryText,
      position: item.position,
      rank_type: 'rank_type' in item ? item.rank_type : rankTab,
      summary: getItemAbstract(item), source_url: getItemUrl(item),
    },
  };
}

export function chipStyle(active: boolean, color: string = '#111827'): React.CSSProperties {
  return {
    borderColor: active ? color : '#E5E7EB',
    background: active ? color : '#FFFFFF',
    color: active ? '#FFFFFF' : '#4B5563',
  };
}

export function formatDate(value: string): string {
  const [, month, day] = value.split('-');
  return `${Number(month)}.${Number(day)}`;
}