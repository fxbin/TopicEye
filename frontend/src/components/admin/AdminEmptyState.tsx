'use client';

import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { Inbox } from 'lucide-react';
import { cx } from '@/components/ui';

/**
 * 后台统一空态（#121 圆桌规范）：空态 = 一句「为什么为空」+ 一个主动作按钮，
 * 禁纯插画。原因让操作者判断是否正常，动作给恢复路径。
 */
export function AdminEmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  compact = false,
  className,
}: {
  /** 可选图标，默认收件箱。 */
  icon?: LucideIcon;
  /** 为什么为空（如「没有匹配的信源」）。 */
  title: string;
  /** 补充说明（如「试试调整筛选条件」）。 */
  description?: string;
  /** 主动作（如「清空筛选」「添加信源」）。 */
  action?: React.ReactNode;
  /** 表格内嵌使用时收敛留白。 */
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cx(
        'flex flex-col items-center justify-center text-center',
        compact ? 'px-6 py-10' : 'px-6 py-16',
        className,
      )}
    >
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-ink-100">
        <Icon size={18} className="text-ink-500" strokeWidth={1.8} />
      </div>
      <div className="text-sm font-medium text-ink-700">{title}</div>
      {description && (
        <p className="mt-1 max-w-[320px] text-xs leading-5 text-ink-500">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
