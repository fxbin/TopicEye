'use client';

import React from 'react';
import { cx } from '@/components/ui';
import { LEVEL_CONFIG_CLASSES } from '@/lib/design-tokens';
import type { RecommendLevel } from '@/types';

interface LevelBadgeProps {
  level: RecommendLevel | string;
  size?: 'normal' | 'small';
}

export default function LevelBadge({ level, size = 'normal' }: LevelBadgeProps) {
  const cfg = LEVEL_CONFIG_CLASSES[level] || LEVEL_CONFIG_CLASSES['不建议追'];
  const isSmall = size === 'small';

  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-semibold',
        isSmall ? 'px-2 py-0.5 text-[11px]' : 'px-3 py-1 text-xs',
        cfg.bg,
        cfg.color,
        cfg.border,
      )}
    >
      <span className={cx('h-1.5 w-1.5 shrink-0 rounded-full', cfg.dot)} />
      {level}
    </span>
  );
}
