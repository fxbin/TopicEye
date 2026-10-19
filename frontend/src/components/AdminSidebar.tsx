'use client';

import React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import {
  Activity,
  BarChart3,
  BookOpen,
  BrainCircuit,
  GitMerge,
  LayoutDashboard,
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
import { ADMIN_NAV_ITEMS as ADMIN_NAV_ENTRIES, ADMIN_NAV_GROUP_LABELS } from '@/lib/admin-nav';

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
  sources: RadioTower,
  contents: Newspaper,
  'content-events': GitMerge,
  users: Users,
  'model-eval': BrainCircuit,
  'mother-topics': BookOpen,
  updates: Rocket,
  monitor: Activity,
  prompts: ScrollText,
  'scoring-dashboard': BarChart3,
  evidence: ShieldCheck,
  feedback: MessageSquareWarning,
  'webhook-logs': Send,
  settings: Settings,
};

// admin 全量导航（含不在 NAV_SPACES 里的 /admin/contents、/admin/mother-topics）。
// href/label/group 来自 @/lib/admin-nav 的唯一清单，顶栏面包屑由同一份派生（#88）。
const ADMIN_NAV_ITEMS: AdminNavItem[] = ADMIN_NAV_ENTRIES.map((entry) => {
  const icon = ADMIN_NAV_ICONS[entry.id];
  if (!icon) {
    throw new Error(`AdminSidebar: 导航项 ${entry.id} 缺少图标映射`);
  }
  return { id: entry.id, label: entry.label, href: entry.href, icon };
});

// 分组渲染结构：概览独立置顶，其余按清单 group 字段聚组（#121 圆桌定稿：
// 领域名词组名 + 频率排序，默认全展开不折叠——折叠把识别变回回忆）。
const NAV_GROUPS: { key: 'content' | 'eval' | 'users' | 'system'; items: AdminNavItem[] }[] = (
  ['content', 'eval', 'users', 'system'] as const
).map((key) => ({
  key,
  items: ADMIN_NAV_ITEMS.filter((item) => ADMIN_NAV_ENTRIES.find((e) => e.id === item.id)?.group === key),
}));

const PINNED_ITEM = ADMIN_NAV_ITEMS[0]; // 概览

export default function AdminSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { currentUser } = useAppContext();

  const isActive = (href: string) => {
    if (href === '/admin') return pathname === '/admin';
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  const renderItem = (item: AdminNavItem) => {
    const active = isActive(item.href);
    const Icon = item.icon;
    return (
      <button
        key={item.id}
        type="button"
        aria-current={active ? 'page' : undefined}
        onClick={() => router.push(item.href)}
        className={cx(
          // #121 规格：14px/高 36px/内距 12px/圆角 6px；hover ink-800；
          // active = 2px 橙左边条 + 文字最高亮度，不叠背景块（避免与徽章抢面积）。
          'relative flex w-full items-center gap-2.5 rounded-xs px-3 py-2 text-left text-sm transition',
          active
            ? 'font-medium text-white'
            : 'font-normal text-ink-500 hover:bg-ink-800 hover:text-white',
        )}
      >
        {active && (
          <span
            aria-hidden="true"
            className="absolute left-0 top-1/2 h-[18px] w-0.5 -translate-y-1/2 rounded-full bg-admin-accent"
          />
        )}
        <Icon size={16} strokeWidth={active ? 2.2 : 1.8} className={active ? 'text-admin-accent' : undefined} />
        <span>{item.label}</span>
      </button>
    );
  };

  return (
    <div className="relative flex h-screen shrink-0 select-none flex-col bg-ink-900 text-ink-500" style={{ width: 220 }}>
      {/* Brand */}
      <div className="px-5 pb-5 pt-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-admin-accent">
            <ShieldCheck size={16} className="text-ink-900" strokeWidth={2.4} />
          </div>
          <div>
            <div className="text-sm font-bold leading-tight text-white">管理后台</div>
            <div className="mt-px text-[10px] tracking-[0.08em] text-ink-500">ADMIN CONSOLE</div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav aria-label="管理后台导航" className="flex-1 overflow-y-auto px-3 pb-4">
        {PINNED_ITEM && (
          <div className="mb-4">{renderItem(PINNED_ITEM)}</div>
        )}
        {NAV_GROUPS.map((group) => (
          <div key={group.key} className="mb-4">
            {/* #121 规格：分组标题 12px/ink-500/大写/字距 0.08em，组间上距 24 下距 8 */}
            <div className="mb-1.5 mt-6 px-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-500 first:mt-0">
              {ADMIN_NAV_GROUP_LABELS[group.key]}
            </div>
            <div className="space-y-0.5">{group.items.map(renderItem)}</div>
          </div>
        ))}
      </nav>

      {/* Bottom User Area：身份展示；会话操作（退出）移至顶栏账号菜单（#121）。 */}
      <div className="border-t border-ink-800 px-5 pb-4 pt-3">
        {currentUser && (
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-ink-300">
                {currentUser.display_name || currentUser.email}
              </div>
              <div className="flex items-center gap-1 text-[10px] text-ink-500">
                <ShieldCheck size={10} strokeWidth={2.4} />
                管理员
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
