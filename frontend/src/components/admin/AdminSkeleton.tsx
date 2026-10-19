'use client';

import React from 'react';
import { cx } from '@/components/ui';

/**
 * 后台表格骨架屏（#121 圆桌规范）：
 * - 首屏加载用保持列宽的骨架，禁全屏 spinner（布局稳定，H1 + 防跳变）
 * - shimmer 1.6s 循环走 globals.css 的 .admin-shimmer，
 *   prefers-reduced-motion 时自动降级为静态块
 */
export function AdminTableSkeleton({
  rows = 6,
  columns = 5,
  className,
}: {
  rows?: number;
  columns?: number;
  className?: string;
}) {
  return (
    <div aria-busy="true" aria-live="polite" className={cx('w-full', className)}>
      {/* 表头骨架：高度对齐 AdminTable 的 40px 表头 */}
      <div className="flex h-10 items-center gap-4 border-b border-ink-200 bg-ink-100 px-4">
        {Array.from({ length: columns }, (_, i) => (
          <div
            key={i}
            className="admin-shimmer h-3 rounded-xs"
            style={{ width: `${Math.max(10, 90 / columns - 4)}%` }}
          />
        ))}
      </div>
      {/* 数据行骨架：高度对齐 48px 行 */}
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex h-12 items-center gap-4 border-b border-ink-100 px-4">
          {Array.from({ length: columns }, (_, col) => (
            <div
              key={col}
              className="admin-shimmer h-3.5 rounded-xs"
              style={{ width: col === 0 ? '26%' : `${Math.max(8, 84 / columns - 3)}%` }}
            />
          ))}
        </div>
      ))}
      <span className="sr-only">正在加载…</span>
    </div>
  );
}

/** 通用块骨架：卡片/表单区加载占位。 */
export function AdminBlockSkeleton({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div aria-busy="true" className={cx('space-y-3 p-4', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="admin-shimmer h-4 rounded-xs"
          style={{ width: i === lines - 1 ? '55%' : `${92 - i * 8}%` }}
        />
      ))}
      <span className="sr-only">正在加载…</span>
    </div>
  );
}
