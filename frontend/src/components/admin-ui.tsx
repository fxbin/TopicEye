'use client';

/**
 * 管理后台统一 UI 原语。
 *
 * 收敛此前散落在 9 个 admin 页面里的 5 种容器写法、4 种标题风格、
 * 3 套通知横幅色系。所有 admin 页面应使用这些原语以保证视觉一致性。
 *
 * - AdminPageShell    统一页面壳（滚动容器 + 响应式内边距 + max-w 居中）
 * - AdminPageHeader   统一标题区（字号 / 字重 / 图标 / 副标题 / 右侧操作）
 * - AdminNoticeBanner 统一通知横幅（teal/red/amber 三色 + 关闭按钮）
 */

import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { X } from 'lucide-react';
import { Panel, cx } from '@/components/ui';

// ─── AdminPageShell ──────────────────────────────────────────────────

/**
 * 管理后台页面壳。
 *
 * 统一规范：
 * - 外层 `h-full overflow-y-auto` 保证内容超长时可滚动
 * - 响应式内边距 `px-4 sm:px-6 lg:px-10`，垂直 `py-5`
 * - 内层 `mx-auto max-w-[xxx] pb-8` 居中 + 底部留白
 *
 * 用法：
 * ```tsx
 * <AdminPageShell>
 *   <AdminPageHeader title="用户管理" ... />
 *   {/* content *\/}
 * </AdminPageShell>
 * ```
 */
export function AdminPageShell({
  children,
  maxWidth = 1100,
  className,
}: {
  children: React.ReactNode;
  /** 内容区最大宽度（px）。默认 1100。 */
  maxWidth?: number;
  className?: string;
}) {
  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page px-4 py-5 sm:px-6 lg:px-10">
      <div
        className={cx('mx-auto w-full space-y-5 pb-8', className)}
        style={{ maxWidth }}
      >
        {children}
      </div>
    </div>
  );
}

// ─── AdminPageHeader ─────────────────────────────────────────────────

/**
 * 管理后台统一标题区。
 *
 * 规范：
 * - H1 字号统一 `text-[26px]`，字重 `font-black`
 * - 可选图标（LucideIcon），放在 H1 左侧
 * - 可选描述文本，`text-sm text-gray-500`
 * - 可选右侧操作区（按钮等）
 *
 * 用法：
 * ```tsx
 * <AdminPageHeader
 *   title="用户管理"
 *   icon={ShieldCheck}
 *   description="管理账号角色、套餐、状态与密码"
 *   actions={<Button>刷新</Button>}
 * />
 * ```
 */
export function AdminPageHeader({
  title,
  icon: Icon,
  description,
  actions,
}: {
  title: string;
  icon?: LucideIcon;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-[26px] font-black leading-tight text-gray-900">
          {Icon && <Icon size={22} className="text-primary" strokeWidth={2.2} />}
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 text-sm leading-6 text-gray-500">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

// ─── AdminNoticeBanner ───────────────────────────────────────────────

type NoticeTone = 'teal' | 'red' | 'amber';

const NOTICE_TONE_CLASS: Record<NoticeTone, string> = {
  teal: 'border-teal-border bg-teal-light text-teal',
  red: 'border-red-border bg-red-light text-red',
  amber: 'border-amber-border bg-amber-light text-amber',
};

/**
 * 管理后台统一通知横幅。
 *
 * 收敛此前散落在各页面的 3 套色系（Tailwind 原生 red-200/teal-200 vs 项目 token red-light/teal-light）
 * 和不一致的 font-bold / 透明度写法。统一使用项目 design token。
 *
 * 用法：
 * ```tsx
 * {error && <AdminNoticeBanner tone="red" onClose={() => setError(null)}>{error}</AdminNoticeBanner>}
 * {notice && <AdminNoticeBanner tone="teal" onClose={() => setNotice(null)}>{notice}</AdminNoticeBanner>}
 * ```
 */
export function AdminNoticeBanner({
  tone,
  children,
  onClose,
  className,
}: {
  tone: NoticeTone;
  children: React.ReactNode;
  onClose?: () => void;
  className?: string;
}) {
  return (
    <Panel className={cx('px-4 py-3', NOTICE_TONE_CLASS[tone], className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-[13px] font-bold leading-6">{children}</div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-sm p-0.5 opacity-60 transition hover:opacity-100"
            aria-label="关闭"
          >
            <X size={14} />
          </button>
        )}
      </div>
    </Panel>
  );
}

// ─── AdminModal ──────────────────────────────────────────────────────

/**
 * 管理后台统一模态对话框。
 *
 * 收敛此前 z-50/z-[1000]、bg-black/30 vs /40、rounded-md vs rounded-lg 的碎片化写法。
 * 统一：z-[1000] + bg-black/30 + Panel(rounded-lg) + 点击遮罩关闭。
 *
 * 用法：
 * ```tsx
 * {showModal && (
 *   <AdminModal title="编辑" onClose={() => setShowModal(false)}>
 *     {/* form content *\/}
 *     <AdminModalFooter>
 *       <Button variant="secondary" onClick={onClose}>取消</Button>
 *       <Button variant="primary" onClick={onSave}>保存</Button>
 *     </AdminModalFooter>
 *   </AdminModal>
 * )}
 * ```
 */
export function AdminModal({
  title,
  children,
  onClose,
  maxWidth = 480,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  maxWidth?: number;
}) {
  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 px-4"
      onClick={onClose}
    >
      <Panel
        onClick={(e) => e.stopPropagation()}
        className="w-full p-6 shadow-2xl"
        style={{ maxWidth }}
      >
        <h2 className="mb-5 text-lg font-black text-gray-900">{title}</h2>
        {children}
      </Panel>
    </div>
  );
}

export function AdminModalFooter({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="mt-5 flex justify-end gap-3">{children}</div>
  );
}
