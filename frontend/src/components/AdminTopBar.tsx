'use client';

import React, { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { ChevronRight, ExternalLink, LogOut, ShieldCheck, UserRound } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { findAdminPageLabel } from '@/lib/admin-nav';

/**
 * 后台顶栏（#121 圆桌规格）：56px 高、白底、下边框 1px ink-200。
 * 职责边界——面包屑（你在哪）+ 返回前台 + 账号菜单（会话操作）。
 * 页面级操作按钮一律不进顶栏：那是各页自己的事，混进来会拖慢任务路径。
 */
export default function AdminTopBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { currentUser, logout } = useAppContext();
  // 页面名由 @/lib/admin-nav 的导航清单派生（#88），不再手写第二份映射表。
  const pageLabel = findAdminPageLabel(pathname);

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    const onClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('mousedown', onClickOutside);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('mousedown', onClickOutside);
    };
  }, [menuOpen]);

  const handleLogout = () => {
    setMenuOpen(false);
    if (logout) {
      void logout();
    }
  };

  return (
    <div className="flex h-14 shrink-0 items-center justify-between border-b border-ink-200 bg-white px-6">
      {/* Breadcrumb：分隔符 ink-300，当前项 ink-900（#121 规格） */}
      <nav aria-label="面包屑" className="flex items-center gap-1.5 text-[13px]">
        <span className="font-bold text-admin-accent">管理后台</span>
        <ChevronRight size={14} className="text-ink-300" strokeWidth={2.2} aria-hidden="true" />
        <span className="font-medium text-ink-900">{pageLabel}</span>
      </nav>

      <div className="flex items-center gap-2">
        {/* 返回前台：管理员的日常是跨前后台跳转，常驻顶栏 */}
        <button
          type="button"
          onClick={() => router.push('/')}
          className="flex items-center gap-1.5 rounded-xs border border-ink-200 bg-white px-3 py-1.5 text-xs font-medium text-ink-700 transition hover:border-ink-300 hover:text-ink-900"
        >
          <ExternalLink size={13} strokeWidth={2} aria-hidden="true" />
          返回前台
        </button>

        {/* 账号菜单：会话操作收敛于此（侧栏底部只留身份展示） */}
        {currentUser && (
          <div ref={menuRef} className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              className="flex items-center gap-1.5 rounded-xs px-2 py-1.5 text-xs font-medium text-ink-700 transition hover:bg-ink-100 hover:text-ink-900"
            >
              <UserRound size={14} strokeWidth={2} aria-hidden="true" />
              <span className="max-w-[160px] truncate">
                {currentUser.display_name || currentUser.email}
              </span>
              <ShieldCheck size={12} className="text-admin-accent" strokeWidth={2.4} aria-hidden="true" />
            </button>
            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 top-[calc(100%+6px)] z-50 w-40 rounded-sm border border-ink-200 bg-white p-1 shadow-lg"
              >
                <button
                  type="button"
                  role="menuitem"
                  onClick={handleLogout}
                  className="flex w-full items-center gap-2 rounded-xs px-2.5 py-2 text-left text-xs font-medium text-red transition hover:bg-red-light"
                >
                  <LogOut size={13} strokeWidth={2} aria-hidden="true" />
                  退出登录
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
