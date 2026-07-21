'use client';

import React from 'react';
import type { LucideIcon } from 'lucide-react';

export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function Panel({
  children,
  className,
  ...props
}: {
  children: React.ReactNode;
  className?: string;
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <section {...props} className={cx('min-w-0 rounded-lg border border-gray-200 bg-white', className)}>
      {children}
    </section>
  );
}

export function Toolbar({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx('flex flex-wrap items-center gap-2', className)}>
      {children}
    </div>
  );
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'success' | 'danger';

export function Button({
  children,
  className,
  variant = 'secondary',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
}) {
  const variantClass: Record<ButtonVariant, string> = {
    primary: 'border-primary-solid bg-primary-solid text-white hover:opacity-90',
    secondary: 'border-gray-200 bg-white text-gray-700 hover:border-primary-border hover:text-primary-text',
    ghost: 'border-transparent bg-transparent text-gray-500 hover:bg-gray-100 hover:text-gray-800',
    success: 'border-teal-border bg-teal-light text-teal-text hover:border-teal-border',
    danger: 'border-red-light bg-red-light text-red hover:border-red/30',
  };

  return (
    <button
      {...props}
      className={cx(
        'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-sm border px-3 py-2 text-xs font-bold transition disabled:cursor-wait disabled:opacity-60',
        variantClass[variant],
        className,
      )}
    >
      {children}
    </button>
  );
}

type BadgeTone = 'neutral' | 'primary' | 'teal' | 'amber' | 'purple' | 'red';

/**
 * 统一色调类型别名。
 *
 * 历史上 `ui.tsx` 用 `BadgeTone`，而 `changelog` / `feedback` / `model-eval`
 * 各自又定义了同值的 `Tone`。这里把 `Tone` 提为公共别名，调用方统一用
 * `import { Tone } from '@/components/ui'`，避免多处重复定义。
 */
export type Tone = BadgeTone;

export function Badge({
  children,
  className,
  tone = 'neutral',
}: {
  children: React.ReactNode;
  className?: string;
  tone?: BadgeTone;
}) {
  const toneClass: Record<BadgeTone, string> = {
    neutral: 'border-gray-200 bg-gray-100 text-gray-600',
    primary: 'border-primary-border bg-primary-light text-primary-text',
    teal: 'border-teal-border bg-teal-light text-teal-text',
    amber: 'border-amber-border bg-amber-light text-amber',
    purple: 'border-purple-border bg-purple-light text-purple',
    red: 'border-red-light bg-red-light text-red',
  };

  return (
    <span className={cx('inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-black', toneClass[tone], className)}>
      {children}
    </span>
  );
}

export function Metric({
  label,
  value,
  icon,
  colorClass = 'text-gray-900',
}: {
  label: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
  colorClass?: string;
}) {
  return (
    <Panel className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-xs font-bold text-gray-500">{label}</div>
        {icon && <div className="flex h-8 w-8 items-center justify-center rounded-sm bg-gray-50">{icon}</div>}
      </div>
      <div className={cx('font-mono text-2xl font-black leading-none', colorClass)}>{value}</div>
    </Panel>
  );
}

// ─── PanelTitle ─────────────────────────────────────────────────────
// 统一收敛此前散落在 stats / trends / today-picks / low-follower-viral /
// trending 等 5+ 处的 PanelTitle 实现。签名取并集：icon + title + hint? + className?。
// 各页迁移时若字号有微差（如 trending 用 text-[13px]，其余用 text-sm），
// 统一以 text-sm 为规范；如需保留原字号可传 className 覆盖。

export function PanelTitle({
  icon: Icon,
  title,
  hint,
  className,
}: {
  /** 可选。不传则不渲染图标——用于图标密度高的模块区，降低视觉噪音。 */
  icon?: LucideIcon;
  title: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cx('mb-3 flex items-center justify-between gap-3', className)}>
      <div className="flex min-w-0 items-center gap-2">
        {Icon && <Icon size={15} className="text-primary" strokeWidth={2.2} />}
        <span className="text-sm font-black text-gray-900">{title}</span>
      </div>
      {hint && <span className="whitespace-nowrap text-[11px] text-gray-400">{hint}</span>}
    </div>
  );
}

// ─── Surface ─────────────────────────────────────────────────────────
// 统一收敛 stats / feedback / model-eval 三处 Surface 实现。
// 规范签名：Panel 容器 + 图标 + 标题 + hint 头部 + children。
// 采用 model-eval 版作为基准（最简洁、自包含）。

export function Surface({
  icon: Icon,
  title,
  hint,
  children,
  className,
}: {
  /** 可选。不传则不渲染图标——用于图标密度高的模块区，降低视觉噪音。 */
  icon?: LucideIcon;
  title: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Panel className={cx('p-4.5 sm:p-5', className)}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {Icon && <Icon size={16} className="shrink-0 text-primary" strokeWidth={2.2} />}
          <span className="truncate text-sm font-black text-gray-900">{title}</span>
        </div>
        {hint && <span className="shrink-0 text-[11px] text-gray-400">{hint}</span>}
      </div>
      {children}
    </Panel>
  );
}

// ─── Segmented ───────────────────────────────────────────────────────
// 从 today-picks/page.tsx 抽出的分段选择器。泛型 <T> 保证 value 类型安全。
// trends/page.tsx ControlPanel 内联的分段按钮迁移时改用本组件。

export function Segmented<T extends string>({
  values,
  active,
  onChange,
  className,
}: {
  values: readonly { value: T; label: string }[];
  active: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div
      className={cx('grid gap-1 rounded-sm bg-gray-100 p-1', className)}
      style={{ gridTemplateColumns: `repeat(${values.length}, 1fr)` }}
    >
      {values.map((item) => {
        const selected = active === item.value;
        return (
          <button
            key={item.value}
            type="button"
            onClick={() => onChange(item.value)}
            className={cx(
              'rounded-xs border border-transparent py-1.5 text-[11px] transition',
              selected
                ? 'bg-white font-black text-primary shadow-sm'
                : 'bg-transparent font-bold text-gray-500 hover:text-gray-800',
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

// ─── FilterLabel ──────────────────────────────────────────────────────
// 从 today-picks/page.tsx 抽出的筛选项标签（图标 + 文本）。

export function FilterLabel({
  icon: Icon,
  children,
  className,
}: {
  icon: LucideIcon;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx('mb-2 flex items-center gap-1.5 text-[11px] font-black text-gray-500', className)}>
      <Icon size={12} strokeWidth={2.2} />
      {children}
    </div>
  );
}
