/**
 * Favorites page 静态配置与工具函数（无 React 依赖）。
 *
 * 包含：
 * - 4 个状态/类型配置数组：TYPE_OPTIONS / STATUS_OPTIONS / STATUS_FLOW /
 *   STATUS_LABEL / TYPE_LABEL / TYPE_TONE / CREATION_PLATFORMS
 * - 5 个工具函数：getSnapshotText / getSnapshotMeta / getFavoriteTags /
 *   parseTagInput / getSavedCreationPlans / withSavedCreationPlan /
 *   getInitialFavoriteFilters
 * - FAVORITES_PAGE_SIZE 常量
 *
 * 与 _components.tsx 配合，主页面只保留 FavoritesPage 状态管理 + JSX 编排。
 */

import type {
  FavoriteItem,
  FavoriteStatus,
  FavoriteTargetType,
} from '@/types';
import type { CreationPlan } from '@/components/CreationPlanDisplay';
import type { LucideIcon } from 'lucide-react';
import { BookText, MessagesSquare, PenLine } from 'lucide-react';

export const TYPE_OPTIONS: Array<{ value: FavoriteTargetType | ''; label: string }> = [
  { value: '', label: '全部类型' },
  { value: 'content', label: '内容' },
  { value: 'source', label: '信源' },
  { value: 'book', label: '小说' },
  { value: 'trend', label: '趋势' },
  { value: 'author', label: '作者' },
  { value: 'topic_group', label: '话题组' },
];

export const STATUS_OPTIONS: Array<{ value: FavoriteStatus | ''; label: string }> = [
  { value: '', label: '全部状态' },
  { value: 'inbox', label: '待处理' },
  { value: 'researching', label: '研究中' },
  { value: 'drafting', label: '创作中' },
  { value: 'archived', label: '已归档' },
];

export const STATUS_FLOW: Array<{
  value: FavoriteStatus;
  label: string;
  hint: string;
  tone: 'amber' | 'teal' | 'primary' | 'neutral';
}> = [
  { value: 'inbox', label: '待处理', hint: '刚收进来的素材', tone: 'amber' },
  { value: 'researching', label: '研究中', hint: '值得拆解和比对', tone: 'teal' },
  { value: 'drafting', label: '创作中', hint: '准备输出成稿', tone: 'primary' },
  { value: 'archived', label: '已归档', hint: '已处理或暂缓', tone: 'neutral' },
];

export const STATUS_LABEL: Record<FavoriteStatus, string> = {
  inbox: '待处理',
  researching: '研究中',
  drafting: '创作中',
  archived: '已归档',
};

export const TYPE_LABEL: Record<FavoriteTargetType, string> = {
  content: '内容',
  book: '小说',
  source: '信源',
  trend: '趋势',
  author: '作者',
  topic_group: '话题组',
};

export const TYPE_TONE: Record<FavoriteTargetType, 'primary' | 'purple' | 'teal' | 'amber' | 'neutral'> = {
  content: 'primary',
  source: 'teal',
  book: 'purple',
  trend: 'amber',
  author: 'neutral',
  topic_group: 'amber',
};

export const CREATION_PLATFORMS: Array<{ id: string; label: string; icon: LucideIcon }> = [
  { id: 'wechat', label: '公众号', icon: BookText },
  { id: 'xiaohongshu', label: '小红书', icon: MessagesSquare },
  { id: 'douyin', label: '抖音', icon: PenLine },
];

export const FAVORITES_PAGE_SIZE = 200;

/** 提取收藏项的摘要文本（去除 HTML 标签，最长 180 字符） */
export function getSnapshotText(item: FavoriteItem): string {
  const snapshot = item.snapshot || {};
  const summary = snapshot.summary;
  if (typeof summary === 'string' && summary.trim()) return summary.replace(/<[^>]+>/g, '').slice(0, 180);
  const category = snapshot.category;
  const platform = snapshot.platform_label || snapshot.platform;
  return [typeof category === 'string' ? category : null, typeof platform === 'string' ? platform : null].filter(Boolean).join(' · ');
}

/** 提取收藏项的元信息（来源/作者/分类/位置） */
export function getSnapshotMeta(item: FavoriteItem): string {
  const snapshot = item.snapshot || {};
  const author = snapshot.author;
  const category = snapshot.category;
  const position = snapshot.position;
  return [
    item.source_name,
    typeof author === 'string' && author ? author : null,
    typeof category === 'string' && category ? category : null,
    typeof position === 'number' ? `#${position}` : null,
  ].filter(Boolean).join(' · ');
}

/** 提取收藏项的 tags（兼容 array 和逗号分隔字符串） */
export function getFavoriteTags(item: FavoriteItem): string[] {
  const rawTags = item.tags;
  if (Array.isArray(rawTags)) return rawTags.map(String).map((tag) => tag.trim()).filter(Boolean);
  if (typeof rawTags === 'string') return rawTags.split(',').map((tag) => tag.trim()).filter(Boolean);
  return [];
}

/** 解析用户输入的 tag 字符串（支持中英文逗号，去重） */
export function parseTagInput(value: string): string[] | null {
  const tags = value.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean);
  return tags.length > 0 ? Array.from(new Set(tags)) : null;
}

/** 提取已保存的创作计划映射 */
export function getSavedCreationPlans(item: FavoriteItem): Record<string, CreationPlan> {
  const rawPlans = item.snapshot?.creation_plans;
  return rawPlans && typeof rawPlans === 'object' && !Array.isArray(rawPlans)
    ? rawPlans as Record<string, CreationPlan>
    : {};
}

/** 合并新的创作计划到 snapshot（带 _saved_at 时间戳） */
export function withSavedCreationPlan(item: FavoriteItem, platform: string, plan: CreationPlan): Record<string, unknown> {
  const snapshot = item.snapshot || {};
  return {
    ...snapshot,
    creation_plans: {
      ...getSavedCreationPlans(item),
      [platform]: {
        ...plan,
        _saved_at: new Date().toISOString(),
      },
    },
  };
}

/** 从 URL query 参数恢复初始过滤条件（用于跨页跳转） */
export function getInitialFavoriteFilters() {
  if (typeof window === 'undefined') {
    return { targetType: '' as FavoriteTargetType | '', status: '' as FavoriteStatus | '', keyword: '' };
  }
  const params = new URLSearchParams(window.location.search);
  return {
    targetType: (params.get('target_type') || '') as FavoriteTargetType | '',
    status: (params.get('status') || '') as FavoriteStatus | '',
    keyword: params.get('keyword') || '',
  };
}