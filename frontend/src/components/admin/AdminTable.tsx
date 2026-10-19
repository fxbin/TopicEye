'use client';

import React from 'react';
import { AlertTriangle, RotateCw } from 'lucide-react';
import { Panel, cx } from '@/components/ui';
import { AdminEmptyState } from './AdminEmptyState';
import { AdminTableSkeleton } from './AdminSkeleton';

/**
 * 后台统一表格原语（#121 圆桌定稿）。
 *
 * 行为契约（页面层禁止自造态）：
 * - loading  → AdminTableSkeleton（保持列宽，禁全屏 spinner）
 * - error    → 表格区内联错误 + 重试按钮（H9：就近可恢复，不弹 Toast）
 * - empty    → AdminEmptyState（为什么为空 + 主动作）
 *
 * 视觉规格：
 * - 表头 40px / 12px·500 / ink-500 / 底 ink-100
 * - 行高 48px / 分隔线 ink-100~200 / hover ink-100 / 选中 primary/8 + 左 2px 橙条
 * - 数字 tabular-nums；操作列右侧粘性（background 随行底变化）
 *
 * 用法：
 * ```tsx
 * <AdminTable
 *   columns={[
 *     { key: 'email', header: '邮箱', render: (u) => u.email },
 *     { key: 'actions', header: '', sticky: 'right', render: (u) => <RowActions row={u} /> },
 *   ]}
 *   rows={users}
 *   rowKey={(u) => u.id}
 *   loading={loading}
 *   error={error}
 *   onRetry={refetch}
 *   empty={<AdminEmptyState title="暂无用户" action={<Button>新建用户</Button>} />}
 * />
 * ```
 */

export interface AdminTableColumn<T> {
  key: string;
  header: React.ReactNode;
  render: (row: T, index: number) => React.ReactNode;
  width?: number | string;
  align?: 'left' | 'right' | 'center';
  /** 操作列：右侧粘性。每张表至多一列。 */
  sticky?: 'right';
  className?: string;
}

export function AdminTable<T>({
  columns,
  rows,
  rowKey,
  loading = false,
  error,
  onRetry,
  empty,
  selectable = false,
  selected = new Set(),
  onSelectedChange,
  batchBar,
  onRowClick,
  minWidth = 720,
  className,
}: {
  columns: AdminTableColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T, index: number) => string | number;
  loading?: boolean;
  /** 非空时渲染内联错误态。 */
  error?: string | null;
  onRetry?: () => void;
  /** 空态内容；传字符串时自动包 AdminEmptyState（compact）。 */
  empty?: React.ReactNode;
  /** 开启行选择（批量操作的前置）。 */
  selectable?: boolean;
  selected?: Set<string | number>;
  onSelectedChange?: (next: Set<string | number>) => void;
  /** 选中行数 > 0 时渲染在表格上方的批量条（常显选中计数）。 */
  batchBar?: React.ReactNode;
  onRowClick?: (row: T) => void;
  /** 表格最小宽度，列多时出横向滚动。 */
  minWidth?: number;
  className?: string;
}) {
  const allKeys = rows.map((row, index) => rowKey(row, index));
  const allSelected = selectable && rows.length > 0 && allKeys.every((key) => selected.has(key));

  const toggleAll = () => {
    if (!onSelectedChange) return;
    const next = new Set(selected);
    if (allSelected) {
      for (const key of allKeys) next.delete(key);
    } else {
      for (const key of allKeys) next.add(key);
    }
    onSelectedChange(next);
  };

  const toggleOne = (key: string | number) => {
    if (!onSelectedChange) return;
    const next = new Set(selected);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    onSelectedChange(next);
  };

  const stickyCount = columns.filter((c) => c.sticky === 'right').length;
  if (stickyCount > 1) {
    throw new Error('AdminTable: 至多一列可声明 sticky: "right"（操作列）');
  }

  const emptyNode =
    empty === undefined || typeof empty === 'string' ? (
      <AdminEmptyState compact title={typeof empty === 'string' ? empty : '暂无数据'} />
    ) : (
      empty
    );

  return (
    <div className={cx('space-y-2', className)}>
      {selectable && selected.size > 0 && batchBar}
      <Panel className={cx('overflow-hidden', loading && 'animate-none')}>
        {loading ? (
          <AdminTableSkeleton columns={columns.length} />
        ) : error ? (
          <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-red-light">
              <AlertTriangle size={18} className="text-red" strokeWidth={1.8} />
            </div>
            <div className="text-sm font-medium text-ink-700">加载失败</div>
            <p className="mt-1 max-w-[360px] break-all text-xs leading-5 text-ink-500">{error}</p>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="mt-3 inline-flex items-center gap-1.5 rounded-xs border border-ink-200 bg-white px-3 py-1.5 text-xs font-medium text-ink-700 transition hover:border-ink-300 hover:text-ink-900"
              >
                <RotateCw size={12} strokeWidth={2} />
                重试
              </button>
            )}
          </div>
        ) : rows.length === 0 ? (
          emptyNode
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm tabular-nums" style={{ minWidth }}>
              <thead>
                <tr className="border-b border-ink-200 bg-ink-100">
                  {selectable && (
                    <th scope="col" className="w-10 px-4 py-2.5 text-left">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        aria-label="全选本页"
                        className="h-3.5 w-3.5 accent-[var(--color-primary-solid)]"
                      />
                    </th>
                  )}
                  {columns.map((column) => (
                    <th
                      key={column.key}
                      scope="col"
                      style={{ width: column.width }}
                      className={cx(
                        'px-4 py-2.5 text-left text-xs font-medium tracking-wide text-ink-500',
                        column.align === 'right' && 'text-right',
                        column.align === 'center' && 'text-center',
                        column.sticky === 'right' && 'sticky right-0 bg-ink-100',
                        column.className,
                      )}
                    >
                      {column.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => {
                  const key = rowKey(row, index);
                  const isSelected = selected.has(key);
                  return (
                    <tr
                      key={key}
                      onClick={onRowClick ? () => onRowClick(row) : undefined}
                      className={cx(
                        'group/group-row border-b border-ink-100 transition-colors last:border-b-0',
                        isSelected ? 'bg-primary/[0.06]' : 'hover:bg-ink-100/60',
                        onRowClick && 'cursor-pointer',
                      )}
                    >
                      {selectable && (
                        <td className="relative px-4 py-0" onClick={(e) => e.stopPropagation()}>
                          {isSelected && (
                            <span
                              aria-hidden="true"
                              className="absolute left-0 top-1/2 h-[18px] w-0.5 -translate-y-1/2 bg-admin-accent"
                            />
                          )}
                          <div className="flex h-12 items-center">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleOne(key)}
                              aria-label={`选择第 ${index + 1} 行`}
                              className="h-3.5 w-3.5 accent-[var(--color-primary-solid)]"
                            />
                          </div>
                        </td>
                      )}
                      {columns.map((column) => (
                        <td
                          key={column.key}
                          className={cx(
                            'px-4 py-0 align-middle',
                            column.align === 'right' && 'text-right',
                            column.align === 'center' && 'text-center',
                            // 粘性列自带底色（随选中/hover 变化），不继承行底
                            column.sticky === 'right' && 'sticky right-0',
                            column.sticky === 'right' &&
                              (isSelected
                                ? 'bg-primary/[0.06]'
                                : 'bg-white group-hover/group-row:bg-ink-100/60'),
                            column.className,
                          )}
                        >
                          <div className="flex h-12 items-center">{column.render(row, index)}</div>
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
