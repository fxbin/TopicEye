'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import { cx } from '@/components/ui';

/**
 * SourceBadge — 信源标注组件。
 *
 * 在内容卡片中显示信源名称，点击跳转到「我的信源」页。
 * 用于"信源透明度"功能：让每条内容的来源可溯源。
 *
 * 使用 useRouter 客户端导航，避免整页刷新。
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
 * 仅使用项目 @theme 中已定义的自定义色（primary / teal / purple / amber / red）
 * 及标准 gray 色阶，避免无效 class 静默不生效。
 * 覆盖 SourceType union 全部成员。
 */
const TYPE_COLORS: Record<string, string> = {
  RSS: 'text-purple',
  RSSHub: 'text-teal',
  Reddit: 'text-amber',
  网站: 'text-amber',
  Zhihu: 'text-primary',
  YouTube: 'text-red',
  X: 'text-gray-500',
  TwitterRSS: 'text-gray-500',
  DouyinHot: 'text-purple',
  API: 'text-primary',
};

export default function SourceBadge({
  name,
  type,
  compact = false,
  fallback,
  className,
}: SourceBadgeProps) {
  const router = useRouter();
  const display = name || fallback;

  if (!display) return null;

  const typeColor = type ? (TYPE_COLORS[type] || 'text-gray-500') : null;
  const fontSize = compact ? 'text-[11px]' : 'text-xs';

  return (
    <span className={cx('inline-flex items-center gap-1.5', fontSize, className)}>
      <span
        role="link"
        tabIndex={0}
        onClick={() => router.push('/sources/me')}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            router.push('/sources/me');
          }
        }}
        className="cursor-pointer font-semibold text-gray-600 transition hover:text-primary"
        title={`查看「${display}」信源详情`}
      >
        {display}
      </span>
      {typeColor && type && (
        <>
          <span className="text-gray-300">·</span>
          <span className={cx('font-medium', typeColor)}>{type}</span>
        </>
      )}
    </span>
  );
}
