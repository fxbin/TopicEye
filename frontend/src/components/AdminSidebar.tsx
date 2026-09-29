'use client';

import React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import {
  Activity,
  ArrowLeft,
  BarChart3,
  BookOpen,
  BrainCircuit,
  GitMerge,
  LayoutDashboard,
  LogOut,
  MessageSquareWarning,
  Newspaper,
  RadioTower,
  Rocket,
  ScrollText,
  Send,
  Settings,
  ShieldCheck,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { cx } from '@/components/ui';
import { useAppContext } from '@/components/ClientLayout';
import { ADMIN_NAV_ITEMS as ADMIN_NAV_ENTRIES } from '@/lib/admin-nav';

interface AdminNavItem {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
}

// 图标是渲染关注点，留在组件侧（@/lib/admin-nav 保持纯逻辑、可在 node 环境测）。
// 缺映射时响亮抛错而不是静默渲染空白——「挂起/未挂载/被跳过」必须显式报错。
const ADMIN_NAV_ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutDashboard,
  monitor: Activity,
  sources: RadioTower,
  contents: Newspaper,
  'content-events': GitMerge,
  users: Users,
  'model-eval': BrainCircuit,
  'mother-topics': BookOpen,
  updates: Rocket,
  prompts: ScrollText,
  'scoring-dashboard': BarChart3,
  evidence: ShieldCheck,
  feedback: MessageSquareWarning,
  'webhook-logs': Send,
  settings: Settings,
};

// admin 全量导航（含不在 NAV_SPACES 里的 /admin/contents、/admin/mother-topics）。
// href/label 来自 @/lib/admin-nav 的唯一清单，顶栏面包屑由同一份派生（#88）。
const ADMIN_NAV_ITEMS: AdminNavItem[] = ADMIN_NAV_ENTRIES.map((entry) => {
  const icon = ADMIN_NAV_ICONS[entry.id];
  if (!icon) {
    throw new Error(`AdminSidebar: 导航项 ${entry.id} 缺少图标映射`);
  }
  return { id: entry.id, label: entry.label, href: entry.href, icon };
});

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
              aria-current={active ? 'page' : undefined}
              onClick={() => {
                if (item.href.startsWith('/dashboard')) {
                  window.open(item.href, '_blank');
                } else {
                  router.push(item.href);
                }
              }}
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
              aria-label="退出登录"
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
