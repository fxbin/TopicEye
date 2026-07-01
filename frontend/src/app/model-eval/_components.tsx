/**
 * Model eval page UI 原子组件。
 *
 * 从 app/model-eval/page.tsx 抽出 7 个可复用 UI 原子：
 * - Surface        面板容器（标题 + 图标 + hint + children）
 * - StatTile       数字统计块（带 tone 着色）
 * - StatusPill     状态徽章（Badge 包装）
 * - FieldLabel     表单字段标签
 * - TextInput      输入框统一样式
 * - SelectInput    下拉框统一样式
 * - InfoCell       信息格子（label + value 组合）
 *
 * 静态配置 + 工具函数来自 _model-eval-utils.ts。
 */

import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { Badge, Panel, cx } from '@/components/ui';
import type { Tone } from './_model-eval-utils';
import { toneClasses } from './_model-eval-utils';

export function Surface({
  title,
  icon: Icon,
  hint,
  children,
  className,
}: {
  title: string;
  icon: LucideIcon;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Panel className={cx('p-4.5 sm:p-5', className)}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon size={16} className="shrink-0 text-primary" strokeWidth={2.2} />
          <span className="truncate text-sm font-black text-gray-900">{title}</span>
        </div>
        {hint && <span className="shrink-0 text-[11px] text-gray-400">{hint}</span>}
      </div>
      {children}
    </Panel>
  );
}

export function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  hint: string;
  tone?: Tone;
}) {
  const toneClass = toneClasses[tone];

  return (
    <div className={cx('min-w-0 rounded-sm border p-3.5', toneClass.bg, toneClass.border)}>
      <div className="mb-2.5 flex items-center gap-2">
        <Icon size={14} className={toneClass.text} strokeWidth={2.2} />
        <span className="truncate text-[11px] font-black text-gray-500">{label}</span>
      </div>
      <div className={cx('font-mono text-2xl font-black leading-none', toneClass.metric)}>{value}</div>
      <div className="mt-1.5 truncate text-[10.5px] text-gray-400">{hint}</div>
    </div>
  );
}

export function StatusPill({
  children,
  tone = 'neutral',
}: {
  children: React.ReactNode;
  tone?: Exclude<Tone, 'purple'>;
}) {
  const badgeTone = tone === 'neutral' ? 'neutral' : tone;
  return (
    <Badge tone={badgeTone} className="gap-1 whitespace-nowrap py-0.5">
      {children}
    </Badge>
  );
}

export function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="mb-1 block text-xs font-bold text-gray-500">{children}</label>;
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        'h-9 w-full rounded-xs border border-gray-200 bg-white px-3 text-[13px] text-gray-800 outline-none transition placeholder:text-gray-300 focus:border-primary-border focus:ring-2 focus:ring-primary-light',
        props.className,
      )}
    />
  );
}

export function SelectInput(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx(
        'h-9 w-full rounded-xs border border-gray-200 bg-white px-3 text-[13px] text-gray-800 outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light',
        props.className,
      )}
    />
  );
}

export function InfoCell({ label, value, muted = false }: { label: string; value: React.ReactNode; muted?: boolean }) {
  return (
    <div className="min-w-0 rounded-xs border border-gray-200 bg-gray-50 px-2.5 py-2">
      <div className="mb-1 truncate text-[10px] text-gray-400">{label}</div>
      <div className={cx('truncate font-mono text-xs font-black', muted ? 'text-gray-400' : 'text-gray-800')}>{value}</div>
    </div>
  );
}