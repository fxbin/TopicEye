'use client';

/** 工作台共享指标卡。页面不再另建同名变体；标签和说明允许自然换行。 */

import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { cx, type Tone } from '@/components/ui';

const TONE_BG: Record<Tone, { border: string; bg: string; text: string }> = {
  neutral: { border: 'border-gray-200', bg: 'bg-white', text: 'text-gray-700' },
  primary: { border: 'border-primary-border', bg: 'bg-primary-light', text: 'text-primary-text' },
  teal: { border: 'border-teal-border', bg: 'bg-teal-light', text: 'text-teal-text' },
  amber: { border: 'border-amber-border', bg: 'bg-amber-light', text: 'text-amber' },
  purple: { border: 'border-purple-border', bg: 'bg-purple-light', text: 'text-purple' },
  red: { border: 'border-red-light', bg: 'bg-red-light', text: 'text-red' },
};

export function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  tone,
  colorClass,
  className,
}: {
  icon?: LucideIcon;
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: Tone;
  colorClass?: string;
  className?: string;
}) {
  const toneClass = tone ? TONE_BG[tone] : TONE_BG.neutral;

  return (
    <div className={cx('min-w-0 rounded-lg border p-4', toneClass.border, toneClass.bg, className)}>
      <div className="mb-2 flex items-center gap-2">
        {Icon && (
          <Icon
            size={14}
            className={colorClass ?? toneClass.text}
            strokeWidth={2.2}
          />
        )}
        <span className="text-xs font-medium text-gray-500">{label}</span>
      </div>
      <div
        className={cx(
          'font-mono text-2xl font-semibold tabular-nums leading-tight',
          tone && tone !== 'neutral' ? toneClass.text : 'text-gray-900',
        )}
      >
        {value}
      </div>
      {hint && <div className="mt-1.5 break-words text-xs leading-5 text-gray-500">{hint}</div>}
    </div>
  );
}
