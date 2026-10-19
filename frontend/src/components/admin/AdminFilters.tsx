'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import { cx } from '@/components/ui';

/**
 * 后台统一筛选行（#121 圆桌规范）：
 * - 搜索 300ms 防抖后提交（onSearchChange 收到的是防抖后的值）
 * - 下拉等筛选控件由 children 传入，保持各页自由度
 * - 已选条件用 chips 呈现（H1 当前过滤状态可见），单 chip 可移除（H6 不靠回忆），
 *   末尾常显「清空全部」（H3 紧急出口）
 *
 * 受控契约：搜索值归父组件所有；本组件只做展示与防抖转发。
 */
export function AdminFilters({
  searchPlaceholder,
  searchValue,
  onSearchChange,
  debounceMs = 300,
  searchClassName,
  children,
  actions,
  className,
}: {
  searchPlaceholder?: string;
  searchValue: string;
  onSearchChange: (value: string) => void;
  debounceMs?: number;
  searchClassName?: string;
  /** 筛选下拉等控件。 */
  children?: React.ReactNode;
  /** 右侧动作区（如导出按钮）。 */
  actions?: React.ReactNode;
  className?: string;
}) {
  const [local, setLocal] = useState(searchValue);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 外部清空（如「清空全部」）时同步输入框
  useEffect(() => {
    setLocal(searchValue);
  }, [searchValue]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleInput = (value: string) => {
    setLocal(value);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => onSearchChange(value), debounceMs);
  };

  return (
    <div className={cx('flex flex-wrap items-center gap-2', className)}>
      <div className={cx('relative', searchClassName)}>
        <Search
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-500"
          strokeWidth={2}
          aria-hidden="true"
        />
        <input
          type="search"
          value={local}
          onChange={(e) => handleInput(e.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder ?? '搜索'}
          className="h-9 w-56 rounded-xs border border-ink-200 bg-white pl-8 pr-3 text-[13px] text-ink-900 placeholder:text-ink-500 focus:border-admin-accent focus:outline-none"
        />
      </div>
      {children}
      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export interface AdminFilterChip {
  key: string;
  label: string;
  onRemove: () => void;
}

/** 已选条件 chips 行：有 chips 才渲染。规格：高 24 / 12px / 圆角 6 / 边框 ink 16%。 */
export function AdminFilterChips({
  chips,
  onClearAll,
  className,
}: {
  chips: readonly AdminFilterChip[];
  onClearAll?: () => void;
  className?: string;
}) {
  if (chips.length === 0) return null;
  return (
    <div className={cx('flex flex-wrap items-center gap-1.5', className)}>
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex h-6 items-center gap-1 rounded-xs border border-ink-900/15 bg-white pl-2 pr-1 text-xs text-ink-700"
        >
          {chip.label}
          <button
            type="button"
            onClick={chip.onRemove}
            aria-label={`移除筛选 ${chip.label}`}
            className="flex h-6 w-6 items-center justify-center rounded-xs text-ink-500 transition hover:bg-ink-900/10 hover:text-ink-900"
          >
            <X size={12} strokeWidth={2.2} />
          </button>
        </span>
      ))}
      {onClearAll && (
        <button
          type="button"
          onClick={onClearAll}
          className="ml-1 h-6 px-1.5 text-xs font-medium text-ink-500 underline-offset-2 transition hover:text-ink-900 hover:underline"
        >
          清空全部
        </button>
      )}
    </div>
  );
}
