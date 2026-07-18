'use client';

/**
 * 通用统计数字块。
 *
 * 收敛此前散落在 4+ 处的「图标 + 标签 + 数值」三件套：
 * - `app/feedback/page.tsx`        StatTile (label, value, icon, tone)
 * - `app/model-eval/_components.tsx` StatTile (icon, label, value, hint, tone)
 * - `app/trending/_components.tsx`  StatTile (icon, label, value, hint, colorClass)
 * - `app/admin/updates/page.tsx`   StatTile (label, value, tone) 无 icon
 *
 * 规范签名取并集：icon? + label + value + hint? + tone? + colorClass? + className?。
 * - 传 `tone` → 用 tone 着色边框/背景/图标（feedback / model-eval 模式）
 * - 传 `colorClass` → 仅着色图标（trending 模式）
 * - 都不传 → 中性灰边框
 *
 * 注：`ui.tsx` 的 `Metric`（Panel 包裹 + 右上角图标圆框）与 `stats/page.tsx`
 * 的 `KpiCard`（带 unit + sub）布局差异较大，不纳入本组件，保留各自实现。
 */

import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { cx, type Tone } from '@/components/ui';

const TONE_BG: Record<Tone, { border: string; bg: string; text: string }> = {
  neutral: { border: 'border-gray-200', bg: 'bg-gray-50', text: 'text-gray-700' },
  primary: { border: 'border-primary-border', bg: 'bg-primary-light', text: 'text-primary' },
  teal: { border: 'border-teal-border', bg: 'bg-teal-light', text: 'text-teal' },
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
    <div className={cx('min-w-0 rounded-sm border p-3.5', toneClass.border, toneClass.bg, className)}>
      <div className="mb-2.5 flex items-center gap-2">
        {Icon && (
          <Icon
            size={14}
            className={colorClass ?? toneClass.text}
            strokeWidth={2.2}
          />
        )}
        <span className="truncate text-[11px] font-black text-gray-500">{label}</span>
      </div>
      <div
        className={cx(
          'font-mono text-2xl font-black leading-none',
          colorClass ?? (tone && tone !== 'neutral' ? toneClass.text : 'text-gray-900'),
        )}
      >
        {value}
      </div>
      {hint && <div className="mt-1.5 truncate text-[10.5px] text-gray-400">{hint}</div>}
    </div>
  );
}
