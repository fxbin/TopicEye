'use client';

import React from 'react';
import { cx } from '@/components/ui';

/**
 * SourceBadge — 信源标注组件。
 *
 * 在内容卡片中显示来源名称与类型。公共内容来源不等于用户私有信源，
 * 仅有名称时不提供管理跳转；查看原文使用卡片既有的原文入口。
 */
interface SourceBadgeProps {
  /** 信源名称 */
  name: string | null | undefined;
  /** 信源类型（可选，显示为颜色标签） */
  type?: string | null | undefined;
  /** 紧凑模式（更小的字号） */
  compact?: boolean;
  /** name 为空时的兜底文本 */
  fallback?: string;
  /** 额外 className */
  className?: string;
}

/**
 * 信源类型 → Tailwind text-* class 映射。
 *
 * 使用项目语义文字色和较深的标准色阶，保持浅色卡片上的可读对比。
 * 覆盖 SourceType union 全部成员。
 */
const TYPE_COLORS: Record<string, string> = {
  RSS: 'text-purple-700',
  RSSHub: 'text-teal-text',
  Reddit: 'text-amber-800',
  网站: 'text-amber-800',
  Zhihu: 'text-primary-text',
  YouTube: 'text-red',
  X: 'text-gray-500',
  TwitterRSS: 'text-gray-500',
  DouyinHot: 'text-purple-700',
  API: 'text-primary-text',
};

export default function SourceBadge({
  name,
  type,
  compact = false,
  fallback,
  className,
}: SourceBadgeProps) {
  const display = name || fallback;

  if (!display) return null;

  const typeColor = type ? (TYPE_COLORS[type] || 'text-gray-500') : null;
  const fontSize = compact ? 'text-xs' : 'text-[13px]';

  return (
    <span className={cx('inline-flex items-center gap-1.5', fontSize, className)}>
      <span className="font-semibold text-gray-600">{display}</span>
      {typeColor && type && (
        <>
          <span className="text-gray-300">·</span>
          <span className={cx('font-medium', typeColor)}>{type}</span>
        </>
      )}
    </span>
  );
}
