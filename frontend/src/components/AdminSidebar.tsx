'use client';

import React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import {
  ArrowLeft,
  BarChart3,
  BookOpen,
  BrainCircuit,
  LayoutDashboard,
  LogOut,
  MessageSquareWarning,
  Newspaper,
  RadioTower,
  Rocket,
  Settings,
  ShieldCheck,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { cx } from '@/components/ui';
import { useAppContext } from '@/components/ClientLayout';

interface AdminNavItem {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
}

// admin 全量导航（含不在 NAV_SPACES 里的 /admin/contents、/admin/mother-topics）
const ADMIN_NAV_ITEMS: AdminNavItem[] = [
  { id: 'dashboard', label: '概览', href: '/admin', icon: LayoutDashboard },
  { id: 'sources', label: '信源管理', href: '/admin/sources', icon: RadioTower },
  { id: 'contents', label: '内容管理', href: '/admin/contents', icon: Newspaper },
  { id: 'users', label: '用户管理', href: '/admin/users', icon: Users },
  { id: 'model-eval', label: 'AI 引擎', href: '/admin/model-eval', icon: BrainCircuit },
  { id: 'mother-topics', label: '系统母题模板库', href: '/admin/mother-topics', icon: BookOpen },
  { id: 'updates', label: '发版记录', href: '/admin/updates', icon: Rocket },
  { id: 'feedback', label: '反馈工作台', href: '/admin/feedback', icon: MessageSquareWarning },
  { id: 'settings', label: '系统设置', href: '/admin/settings', icon: Settings },
];

export default function AdminSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { currentUser, authLoading, logout } = useAppContext();

  const isActive = (href: string) => {
    if (href === '/admin') return pathname === '/admin';
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  const handleLogout = () => {
    if (logout) {
      void logout();
    }
  };

  return (
    <div className="relative flex h-screen shrink-0 select-none flex-col bg-slate-900 text-slate-300" style={{ width: 220 }}>
      {/* Brand */}
      <div className="px-6 pb-6 pt-7">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-500">
            <ShieldCheck size={16} className="text-slate-900" strokeWidth={2.4} />
          </div>
          <div>
            <div className="text-[15px] font-bold leading-tight text-white">
              管理后台
            </div>
            <div className="mt-px text-[10px] tracking-[0.08em] text-slate-500">
              ADMIN CONSOLE
            </div>
          </div>
        </div>
      </div>

      {/* Back to user side */}
      <div className="px-3 pb-3">
        <button
          type="button"
          onClick={() => router.push('/')}
          className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-xs text-slate-400 transition hover:bg-slate-800 hover:text-white"
        >
          <ArrowLeft size={14} strokeWidth={2} />
          返回用户侧
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3">
        {ADMIN_NAV_ITEMS.map((item) => {
          const active = isActive(item.href);
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => router.push(item.href)}
              className={cx(
                'mb-0.5 flex w-full items-center gap-2 rounded-sm px-3 py-2.5 text-left text-sm transition',
                active
                  ? 'bg-amber-500/15 font-semibold text-amber-400'
                  : 'font-normal text-slate-400 hover:bg-slate-800 hover:text-white',
              )}
            >
              <Icon size={16} strokeWidth={active ? 2.2 : 1.8} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Bottom User Area */}
      <div className="border-t border-slate-800 px-3 pb-4 pt-3">
        {currentUser && (
          <div className="flex items-center justify-between gap-2 px-3">
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-slate-300">
                {currentUser.display_name || currentUser.email}
              </div>
              <div className="flex items-center gap-1 text-[10px] text-amber-500">
                <ShieldCheck size={10} strokeWidth={2.4} />
                管理员
              </div>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              disabled={authLoading}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-slate-500 transition hover:bg-slate-800 hover:text-red-400"
              title="退出登录"
            >
              <LogOut size={14} strokeWidth={2} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
