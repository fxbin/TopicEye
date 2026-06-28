'use client';

/**
 * 统一的空态 / 加载态 / 错误态 展示组件。
 *
 * 收敛此前散落在各 page.tsx 里的 6+ 处 EmptyState、3 套 spinner 实现、
 * 2 种错误横幅。调用方根据状态选择渲染 <LoadingState> / <EmptyState> /
 * <ErrorState>，或用 <StateView> 一站式按 loading/error/empty 自动切换。
 */

import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { Inbox, Loader2, AlertCircle, X } from 'lucide-react';
import { Panel, Button, cx } from '@/components/ui';

export type StateAction = {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary' | 'ghost';
};

const ACTION_TITLE_CLS = 'text-[15px] font-black text-gray-700';
const ACTION_DESC_CLS = 'mt-1.5 text-xs text-gray-400';
const ICON_CLS = 'text-gray-300';

type WrapperProps = {
  children: React.ReactNode;
  className?: string;
  /** 是否包裹 Panel（带边框卡片）。默认 true。 */
  panel?: boolean;
  minHeight?: string;
};

function StateWrapper({ children, className, panel = true, minHeight }: WrapperProps) {
  const style = minHeight ? { minHeight } : undefined;
  const content = (
    <div
      style={style}
      className={cx('grid place-items-center p-8 text-center', className)}
    >
      {children}
    </div>
  );
  return panel ? <Panel className="min-w-0">{content}</Panel> : content;
}

// ─── LoadingState ────────────────────────────────────────────────────

export function LoadingState({
  label = '加载中…',
  className,
  panel = false,
  minHeight,
}: {
  label?: string;
  className?: string;
  panel?: boolean;
  minHeight?: string;
}) {
  return (
    <StateWrapper panel={panel} minHeight={minHeight} className={className}>
      <div className="flex items-center justify-center gap-2.5 text-gray-400">
        <Loader2 size={18} className="animate-spin" />
        <span className="text-[13px]">{label}</span>
      </div>
    </StateWrapper>
  );
}

// ─── EmptyState ──────────────────────────────────────────────────────

export function EmptyState({
  icon: Icon,
  title,
  desc,
  children,
  actions,
  className,
  panel = true,
  minHeight,
}: {
  icon?: LucideIcon;
  title?: string;
  desc?: string;
  children?: React.ReactNode;
  actions?: StateAction[];
  className?: string;
  panel?: boolean;
  minHeight?: string;
}) {
  return (
    <StateWrapper panel={panel} minHeight={minHeight} className={className}>
      <div className="space-y-3">
        {Icon && <div className="flex justify-center"><Icon size={32} className={ICON_CLS} /></div>}
        {title && <div className={ACTION_TITLE_CLS}>{title}</div>}
        {desc && <div className={ACTION_DESC_CLS}>{desc}</div>}
        {children}
        {actions && actions.length > 0 && (
          <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
            {actions.map((a) => (
              <Button key={a.label} variant={a.variant} onClick={a.onClick}>
                {a.label}
              </Button>
            ))}
          </div>
        )}
      </div>
    </StateWrapper>
  );
}

// ─── ErrorState ──────────────────────────────────────────────────────

export function ErrorState({
  error,
  onRetry,
  onDismiss,
  className,
  panel = false,
}: {
  error: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
  panel?: boolean;
}) {
  return (
    <StateWrapper panel={panel} className={className}>
      <div
        className={cx(
          'flex w-full items-center justify-between gap-3 rounded-sm bg-red-light px-4 py-2.5 text-[13px] text-red',
        )}
      >
        <span className="flex items-center gap-2">
          <AlertCircle size={15} className="shrink-0" />
          <span>{error}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="font-bold underline-offset-2 hover:underline"
            >
              重试
            </button>
          )}
          {onDismiss && (
            <button type="button" onClick={onDismiss} aria-label="关闭">
              <X size={14} />
            </button>
          )}
        </span>
      </div>
    </StateWrapper>
  );
}

// ─── StateView（一站式，按状态自动切换） ────────────────────────────

export function StateView({
  loading,
  error,
  empty,
  onRetry,
  onDismiss,
  children,
  loadingLabel,
  emptyIcon = Inbox,
  emptyTitle,
  emptyDesc,
  minHeight,
}: {
  loading: boolean;
  error: string | null;
  empty: boolean;
  onRetry?: () => void;
  onDismiss?: () => void;
  children?: React.ReactNode;
  loadingLabel?: string;
  emptyIcon?: LucideIcon;
  emptyTitle?: string;
  emptyDesc?: string;
  minHeight?: string;
}) {
  if (loading) return <LoadingState label={loadingLabel} minHeight={minHeight} />;
  if (error) return <ErrorState error={error} onRetry={onRetry} onDismiss={onDismiss} />;
  if (empty) {
    return (
      <EmptyState
        icon={emptyIcon}
        title={emptyTitle}
        desc={emptyDesc}
        minHeight={minHeight}
      />
    );
  }
  return <>{children}</>;
}
