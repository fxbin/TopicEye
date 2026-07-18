'use client';

/**
 * 通用分页组件。
 *
 * 收敛此前散落在 3 处的分页实现：
 * - `app/low-follower-viral/page.tsx` 最完整版（页码窗口 + 上下页 + PageButton）
 * - `app/weread/page.tsx`             简版（上下页 + 当前/总数文本）
 * - `app/contents/page.tsx`           简版（上下页 + 页码文本）
 *
 * 规范签名以 low-follower-viral 版为基准，额外提供 `summary?: React.ReactNode`
 * 用于在左侧渲染自定义统计文本（如「第 1 / 5 页，共 234 条」）。
 * `onPage` 支持 updater 函数形式，兼容 `setPage(prev => ...)` 调用模式。
 */

import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button, cx } from '@/components/ui';

function PageButton({
  disabled,
  onClick,
  children,
}: {
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      disabled={disabled}
      variant="secondary"
      className={cx('px-3.5 py-2 text-[13px]', disabled && 'cursor-not-allowed bg-gray-50 text-gray-300')}
    >
      {children}
    </Button>
  );
}

export function Pagination({
  page,
  totalPages,
  onPage,
  summary,
  className,
}: {
  page: number;
  totalPages: number;
  onPage: (updater: number | ((page: number) => number)) => void;
  summary?: React.ReactNode;
  className?: string;
}) {
  // 计算最多 5 个页码窗口，始终围绕当前页
  const pageNumbers = Array.from({ length: Math.min(5, totalPages) }, (_, index) => {
    if (totalPages <= 5) return index + 1;
    if (page <= 3) return index + 1;
    if (page >= totalPages - 2) return totalPages - 4 + index;
    return page - 2 + index;
  });

  return (
    <div className={cx('mt-6 flex items-center justify-between gap-3', className)}>
      {summary && <span className="text-[13px] text-gray-500">{summary}</span>}
      <div className="ml-auto flex items-center gap-3">
        <div className="flex gap-1">
          {pageNumbers.map((pageNumber) => {
            const active = page === pageNumber;
            return (
              <button
                key={pageNumber}
                type="button"
                onClick={() => onPage(pageNumber)}
                className={cx(
                  'h-8 w-8 rounded-sm border text-[13px] transition',
                  active
                    ? 'border-primary-border bg-primary font-black text-white'
                    : 'border-gray-200 bg-white font-bold text-gray-600 hover:border-primary-border hover:text-primary',
                )}
              >
                {pageNumber}
              </button>
            );
          })}
        </div>
        <div className="flex gap-2">
          <PageButton disabled={page === 1} onClick={() => onPage((current) => Math.max(1, current - 1))}>
            <ChevronLeft size={14} /> 上一页
          </PageButton>
          <PageButton disabled={page === totalPages} onClick={() => onPage((current) => Math.min(totalPages, current + 1))}>
            下一页 <ChevronRight size={14} />
          </PageButton>
        </div>
      </div>
    </div>
  );
}
