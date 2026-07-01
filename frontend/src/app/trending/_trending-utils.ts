/**
 * Trending page 静态配置与工具函数。
 *
 * 从 app/trending/page.tsx 抽出：
 * - CATEGORIES  分类选项
 * - SOURCE_BRAND / SOURCE_LABELS  数据源品牌颜色 + 显示名
 * - sourceBrand()  查找数据源品牌（fallback 默认灰色）
 * - CATEGORY_COLORS  分类颜色映射
 * - isWebnovelSource()  网文来源判定
 * - TREND_ICONS / RESONANCE_COLORS  趋势/共鸣度视觉映射（在子组件 _components.tsx 用）
 *
 * 子组件 _components.tsx 依赖本模块，page.tsx 通过 re-export 保持外部 import 路径不变。
 */

import { Headphones, MessageCircle, Newspaper, TrendingUp, Flame } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export const CATEGORIES = [
  { value: '', label: '全部' },
  { value: 'hot', label: '热点' },
  { value: 'tech', label: '科技' },
  { value: 'finance', label: '财经' },
  { value: 'webnovel', label: '网文' },
  { value: 'podcast', label: '播客' },
  { value: 'community', label: '社区' },
  { value: 'entertainment', label: '娱乐' },
] as const;

export const SOURCE_BRAND: Record<string, { label: string; color: string; bg: string }> = {
  weibo:       { label: '微博',     color: '#FF8200', bg: '#FFF7EB' },
  baidu:       { label: '百度',     color: '#306CFF', bg: '#EBF1FF' },
  douyin:      { label: '抖音',     color: '#161823', bg: '#F5F5F7' },
  toutiao:     { label: '头条',     color: '#F85959', bg: '#FFF0F0' },
  zhihu:       { label: '知乎',     color: '#0066FF', bg: '#EBF2FF' },
  bilibili:    { label: 'B站',      color: '#FB7299', bg: '#FFF0F5' },
  hackernews:  { label: 'HN',       color: '#FF6600', bg: '#FFF5EB' },
  ithome:      { label: 'IT之家',   color: '#D22222', bg: '#FFF0F0' },
  juejin:      { label: '掘金',     color: '#1E80FF', bg: '#EBF3FF' },
  eastmoney:   { label: '东方财富', color: '#D4940A', bg: '#FFF8E8' },
  douban:      { label: '豆瓣',     color: '#00B51D', bg: '#EEFBF0' },
  tieba:       { label: '贴吧',     color: '#4E6EF2', bg: '#EEF1FD' },
  netease:     { label: '网易',     color: '#C03A3A', bg: '#FDF0F0' },
  v2ex:        { label: 'V2EX',     color: '#333333', bg: '#F0F0F0' },
  github:      { label: 'GitHub',   color: '#24292F', bg: '#F0F1F3' },
  sspai:       { label: '少数派',   color: '#D6192B', bg: '#FDF0F0' },
  xueqiu:      { label: '雪球',     color: '#1478FF', bg: '#ECF3FF' },
  sohu:        { label: '搜狐',     color: '#D8503C', bg: '#FDF0EF' },
  hupu:        { label: '虎扑',     color: '#D43030', bg: '#FDF0F0' },
  kr36:        { label: '36氪',     color: '#0080FF', bg: '#ECF3FF' },
  heiyan:      { label: '黑岩',     color: '#A855F7', bg: '#F5F0FF' },
  ishugui:     { label: '点众',     color: '#0EA5E9', bg: '#EBF8FF' },
  xyzrank:     { label: '播客榜',   color: '#9333EA', bg: '#F5F0FF' },
};

export function sourceBrand(source: string) {
  return SOURCE_BRAND[source] || { label: source, color: '#4B5563', bg: '#F3F4F6' };
}

export const SOURCE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(SOURCE_BRAND).map(([k, v]) => [k, v.label])
);

export const CATEGORY_COLORS: Record<string, { bgClass: string; textClass: string; borderClass: string }> = {
  hot: { bgClass: 'bg-primary-light', textClass: 'text-primary', borderClass: 'border-primary-border' },
  tech: { bgClass: 'bg-teal-light', textClass: 'text-teal', borderClass: 'border-teal-border' },
  finance: { bgClass: 'bg-amber-light', textClass: 'text-amber', borderClass: 'border-amber-border' },
  webnovel: { bgClass: 'bg-purple-light', textClass: 'text-purple', borderClass: 'border-purple-border' },
  podcast: { bgClass: 'bg-purple-light', textClass: 'text-purple', borderClass: 'border-purple-border' },
  community: { bgClass: 'bg-teal-light', textClass: 'text-teal', borderClass: 'border-teal-border' },
  entertainment: { bgClass: 'bg-amber-light', textClass: 'text-amber', borderClass: 'border-amber-border' },
};

/** 是否为网文类目（走 bookId/cover/author/tags 字段而非纯 hot_value） */
export function isWebnovelSource(source: string): boolean {
  return source === 'heiyan' || source === 'ishugui';
}

/** 趋势方向图标（up / down / new / stable） */
export const TREND_ICONS: Record<string, LucideIcon> = {
  up: TrendingUp,
  down: MessageCircle,
  new: Flame,
  stable: Newspaper,
  podcast: Headphones,
};

/** 共鸣度（跨平台聚类信号强度）颜色映射 */
export const RESONANCE_COLORS: Record<number, { bgClass: string; textClass: string; borderClass: string; label: string }> = {
  0: { bgClass: 'bg-gray-50', textClass: 'text-gray-400', borderClass: 'border-gray-200', label: '安静' },
  1: { bgClass: 'bg-amber-light', textClass: 'text-amber', borderClass: 'border-amber-border', label: '初现' },
  2: { bgClass: 'bg-primary-light', textClass: 'text-primary', borderClass: 'border-primary-border', label: '升温' },
  3: { bgClass: 'bg-teal-light', textClass: 'text-teal', borderClass: 'border-teal-border', label: '共振' },
};