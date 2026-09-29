'use client';

import React from 'react';
import { usePathname } from 'next/navigation';
import { ChevronRight, ShieldCheck } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { findAdminPageLabel } from '@/lib/admin-nav';

export default function AdminTopBar() {
  const pathname = usePathname();
  const { currentUser } = useAppContext();
  // 页面名由 @/lib/admin-nav 的导航清单派生（#88），不再手写第二份映射表。
  // 此前两份目录互相矛盾（侧边栏 15 项 / 面包屑 10 条），4 个页面的顶栏
  // 回退显示兜底文案「管理」，与侧边栏自相矛盾。
  const pageLabel = findAdminPageLabel(pathname);

  return (
    <div className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-[13px]">
        <span className="font-bold text-amber-600">管理后台</span>
        <ChevronRight size={14} className="text-gray-300" strokeWidth={2.2} />
        <span className="font-medium text-gray-700">{pageLabel}</span>
      </nav>

      {/* Admin badge */}
      {currentUser && (
        <div className="flex items-center gap-1.5 rounded-sm bg-amber-50 px-2.5 py-1 text-[11px] font-bold text-amber-700">
          <ShieldCheck size={12} strokeWidth={2.4} />
          {currentUser.display_name || currentUser.email}
        </div>
      )}
    </div>
  );
}
