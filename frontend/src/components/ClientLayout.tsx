'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { usePathname } from 'next/navigation';
import Sidebar from '@/components/Sidebar';
import { Menu } from 'lucide-react';
import NavigationDrawer from '@/components/NavigationDrawer';
import { visibleNavSpaces } from '@/lib/navigation';
import NotificationBell from '@/components/NotificationBell';
import { AppProvider, useAuthContext, useFavoritesContext, useAppContext } from '@/providers/AppProvider';
import type { PrefetchData } from '@/lib/server-prefetch';

// Backward compat: 38 个消费者从 @/components/ClientLayout 导入 useAppContext
export { useAppContext };

// 无侧边栏的整屏页：登录页与 MCP 授权同意页（弹窗场景，只要居中卡片）
const CHROMELESS_PATHS = new Set(['/login', '/mcp/authorize', '/oauth/callback']);
const ADMIN_PATH_PREFIX = '/admin';

/**
 * ClientLayout — 根布局壳。
 *
 * 状态管理已拆分到独立 Provider（见 providers/）：
 * - AuthProvider      — 用户认证、功能开关、路由守卫
 * - FavoritesProvider — 收藏状态、侧边栏计数
 * - ReaderProvider    — 全局站内阅读抽屉
 *
 * 本组件只负责布局 chrome 渲染（Sidebar / NotificationBell）和 compactNav 响应式状态。
 */
export default function ClientLayout({
  children,
  initialData,
}: {
  children: React.ReactNode;
  initialData: PrefetchData;
}) {
  return (
    <AppProvider initialData={initialData}>
      <LayoutChrome>{children}</LayoutChrome>
    </AppProvider>
  );
}

function LayoutChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { currentUser, authLoading, enabledFeatures, logout } = useAuthContext();
  const { topicCount, todayPicksCount, favoriteTotal, sourceCount } = useFavoritesContext();
  const [compactNav, setCompactNav] = useState(false);
  const [drawerPath, setDrawerPath] = useState<string | null>(null);
  const closeDrawer = useCallback(() => setDrawerPath(null), []);
  const detailLabel = pathname === '/profile' ? '个人中心' : pathname.startsWith('/contents/') ? '站内阅读' : pathname.startsWith('/topics/') ? '选题详情' : pathname === '/my-topics/config' ? '母题配置' : null;
  const pageLabel = detailLabel || visibleNavSpaces(currentUser, enabledFeatures).flatMap(space => space.items)
    .filter(item => item.href === '/' ? pathname === '/' : pathname === item.href || pathname.startsWith(`${item.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0]?.label || '选题雷达';

  const isChromelessPath = CHROMELESS_PATHS.has(pathname);
  const isAdminPath = pathname === ADMIN_PATH_PREFIX || pathname.startsWith(`${ADMIN_PATH_PREFIX}/`);

  useEffect(() => {
    const updateCompact = () => setCompactNav(window.innerWidth < 1100);
    updateCompact();
    window.addEventListener('resize', updateCompact);
    return () => window.removeEventListener('resize', updateCompact);
  }, []);

  if (isChromelessPath) {
    return (
      <main className="h-dvh overflow-hidden bg-page">
        {children}
      </main>
    );
  }

  if (isAdminPath) {
    // admin 路径由 app/admin/layout.tsx 接管壳，这里只保留 context
    return (
      <main className="h-dvh overflow-hidden bg-page">
        {children}
      </main>
    );
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <div className="hidden h-full shrink-0 md:block"><Sidebar topicCount={topicCount} todayPicksCount={todayPicksCount} favCount={favoriteTotal}
          sourceCount={sourceCount} currentUser={currentUser} authLoading={authLoading}
          enabledFeatures={enabledFeatures} onLogout={logout} compact={compactNav} /></div>
      <NavigationDrawer open={drawerPath === pathname} onClose={closeDrawer} label="选题雷达导航">
        <div className="h-full [&>div]:!w-full"><Sidebar topicCount={topicCount} todayPicksCount={todayPicksCount} favCount={favoriteTotal}
          sourceCount={sourceCount} currentUser={currentUser} authLoading={authLoading}
          enabledFeatures={enabledFeatures} onLogout={logout} onNavigate={closeDrawer} /></div>
      </NavigationDrawer>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-page">
        <div className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-gray-100 bg-white px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button type="button" onClick={() => setDrawerPath(pathname)} aria-label="打开导航" aria-haspopup="dialog" aria-expanded={drawerPath === pathname}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-sm text-gray-700 hover:bg-gray-100 md:hidden"><Menu size={21} /></button>
            <span className="truncate text-sm font-medium text-gray-700">{pageLabel}</span>
          </div>
          {currentUser && <NotificationBell />}
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
