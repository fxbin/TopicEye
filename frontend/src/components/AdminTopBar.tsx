'use client';

import React from 'react';
import { usePathname } from 'next/navigation';
import { ChevronRight, ShieldCheck } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';

// 路径 → 页面名映射（面包屑用）
const ADMIN_PAGE_LABELS: Record<string, string> = {
  '/admin': '概览',
  '/admin/sources': '信源管理',
  '/admin/contents': '内容管理',
  '/admin/users': '用户管理',
  '/admin/model-eval': 'AI 引擎',
  '/admin/mother-topics': '系统母题模板库',
  '/admin/updates': '发版记录',
  '/admin/feedback': '反馈工作台',
  '/admin/settings': '系统设置',
};

function findPageLabel(pathname: string): string {
  // 精确匹配
  if (ADMIN_PAGE_LABELS[pathname]) return ADMIN_PAGE_LABELS[pathname];
  // 前缀匹配（子路径）
  const sorted = Object.keys(ADMIN_PAGE_LABELS).sort((a, b) => b.length - a.length);
  for (const key of sorted) {
    if (pathname.startsWith(`${key}/`)) return ADMIN_PAGE_LABELS[key];
  }
  return '管理';
}

export default function AdminTopBar() {
  const pathname = usePathname();
  const { currentUser } = useAppContext();
  const pageLabel = findPageLabel(pathname);

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
