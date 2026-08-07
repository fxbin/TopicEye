'use client';

import React, { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import Sidebar from '@/components/Sidebar';
import NotificationBell from '@/components/NotificationBell';
import { AppProvider, useAuthContext, useFavoritesContext, useAppContext } from '@/providers/AppProvider';

// Backward compat: 38 个消费者从 @/components/ClientLayout 导入 useAppContext
export { useAppContext };

const CHROMELESS_PATHS = new Set(['/login']);
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
export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <LayoutChrome>{children}</LayoutChrome>
    </AppProvider>
  );
}

function LayoutChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { currentUser, authLoading, enabledFeatures, logout } = useAuthContext();
  const { topicCount, todayPicksCount, favoriteTotal, sourceCount } = useFavoritesContext();
  const [compactNav, setCompactNav] = useState(false);

  const isChromelessPath = CHROMELESS_PATHS.has(pathname);
  const isAdminPath = pathname === ADMIN_PATH_PREFIX || pathname.startsWith(`${ADMIN_PATH_PREFIX}/`);

  useEffect(() => {
    const updateCompact = () => setCompactNav(window.innerWidth < 900);
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
      <Sidebar
        topicCount={topicCount}
        todayPicksCount={todayPicksCount}
        favCount={favoriteTotal}
        sourceCount={sourceCount}
        compact={compactNav}
        currentUser={currentUser}
        authLoading={authLoading}
        enabledFeatures={enabledFeatures}
        onLogout={logout}
      />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-page">
        <div className="flex h-12 shrink-0 items-center justify-end border-b border-gray-100 bg-white px-6">
          {currentUser && <NotificationBell />}
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
