'use client';

/**
 * 通用内联通知条。
 *
 * 收敛此前散落在 2 处的 `(error || notice) && <div>` 模式：
 * - `app/feedback/page.tsx`   `(formError || notice)` 红绿双色条
 * - `app/changelog/page.tsx`  `FeedbackPanel` 内 `(error || notice)` 红绿双色条
 *
 * 规范三态：`error`（红）/ `success`（青）/ `info`（灰）。
 * 调用方传 `children` 作为文案，组件负责配色与边框。
 */

import React from 'react';
import { cx } from '@/components/ui';

export type NoticeTone = 'error' | 'success' | 'info';

const TONE_CLASS: Record<NoticeTone, string> = {
  error: 'border-red-light bg-red-light text-red',
  success: 'border-teal-border bg-teal-light text-teal',
  info: 'border-gray-200 bg-gray-50 text-gray-600',
};

export function NoticeBar({
  children,
  tone = 'info',
  className,
}: {
  children: React.ReactNode;
  tone?: NoticeTone;
  className?: string;
}) {
  return (
    <div className={cx('rounded-sm border px-3 py-2 text-[13px] font-bold', TONE_CLASS[tone], className)}>
      {children}
    </div>
  );
}
