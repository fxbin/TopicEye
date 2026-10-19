'use client';

/**
 * 通用分页组件。
 *
 * 供内容列表和阅读页面复用页码窗口、上下页与统计文本。
 *
 * `summary?: React.ReactNode` 用于在左侧渲染自定义统计文本
 * （如「第 1 / 5 页，共 234 条」）。
 * `onPage` 支持 updater 函数形式，兼容 `setPage(prev => ...)` 调用模式。
 *
 * #121 后台改版升级（全部可选、向后兼容）：总页数 > 5 时显示跳页输入；
 * 传入 `pageSize` + `onPageSizeChange` 时显示每页条数选择器（10/20/50）。
 */

import React, { useState } from 'react';
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

const PAGE_SIZE_OPTIONS = [10, 20, 50] as const;

export function Pagination({
  page,
  totalPages,
  onPage,
  summary,
  pageSize,
  pageSizeOptions,
  onPageSizeChange,
  className,
}: {
  page: number;
  totalPages: number;
  onPage: (updater: number | ((page: number) => number)) => void;
  summary?: React.ReactNode;
  /** 每页条数。与 onPageSizeChange 同时传入才显示条数选择器。 */
  pageSize?: number;
  /** 可选的自定义档位，默认 10/20/50。 */
  pageSizeOptions?: readonly number[];
  onPageSizeChange?: (pageSize: number) => void;
  className?: string;
}) {
  const [jumpValue, setJumpValue] = useState('');
  const showJump = totalPages > 5;
  const showPageSize = pageSize != null && onPageSizeChange != null;
  const options = pageSizeOptions ?? PAGE_SIZE_OPTIONS;

  const jumpToPage = () => {
    const target = Number.parseInt(jumpValue, 10);
    if (Number.isFinite(target)) {
      const clamped = Math.min(Math.max(1, target), Math.max(1, totalPages));
      onPage(clamped);
    }
    setJumpValue('');
  };

  // 计算最多 5 个页码窗口，始终围绕当前页
  const pageNumbers = Array.from({ length: Math.min(5, totalPages) }, (_, index) => {
    if (totalPages <= 5) return index + 1;
    if (page <= 3) return index + 1;
    if (page >= totalPages - 2) return totalPages - 4 + index;
    return page - 2 + index;
  });

  return (
    <div className={cx('mt-6 flex flex-wrap items-center justify-between gap-3', className)}>
      {summary && <span className="text-[13px] text-gray-500">{summary}</span>}
      <div className="ml-auto flex flex-wrap items-center gap-3">
        {showPageSize && (
          <label className="flex items-center gap-1.5 text-[13px] text-gray-500">
            每页
            <select
              value={pageSize}
              onChange={(e) => onPageSizeChange?.(Number(e.target.value))}
              aria-label="每页条数"
              className="h-8 rounded-sm border border-gray-200 bg-white px-1.5 text-[13px] text-gray-700"
            >
              {options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            条
          </label>
        )}
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
        {showJump && (
          <div className="flex items-center gap-1 text-[13px] text-gray-500">
            跳至
            <input
              type="number"
              min={1}
              max={totalPages}
              value={jumpValue}
              onChange={(e) => setJumpValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') jumpToPage();
              }}
              onBlur={() => setJumpValue('')}
              aria-label={`跳转页码（1-${totalPages}）`}
              className="h-8 w-14 rounded-sm border border-gray-200 bg-white px-2 text-center text-[13px] text-gray-700 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
            页
          </div>
        )}
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
