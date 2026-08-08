'use client';

import React, { createContext, useContext, useEffect, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useStore } from 'zustand';
import {
  createFavoritesStore,
  type FavoritesStore,
  type FavoritesState,
  type FavoritesContextType,
} from '@/stores/favoritesStore';
import { useAuthStoreApi } from './AuthProvider';

// ── Context: holds the per-instance store ─────────────────────

const FavoritesStoreContext = createContext<FavoritesStore | null>(null);

// ── Hooks ─────────────────────────────────────────────────────

/**
 * 细粒度 selector hook（新代码推荐使用）。
 * 只在选中的 state slice 变化时 re-render。
 *
 * @example
 * const favorites = useFavoritesStore(s => s.favorites);
 * const toggleFavorite = useFavoritesStore(s => s.toggleFavorite);
 */
export function useFavoritesStore<T>(selector: (s: FavoritesState) => T): T {
  const store = useContext(FavoritesStoreContext);
  if (!store) throw new Error('useFavoritesStore must be used within FavoritesProvider');
  return useStore(store, selector);
}

/**
 * 向后兼容 hook：订阅整个 favorites store（与原 useContext(FavoritesContext) 行为一致）。
 */
export function useFavoritesContext(): FavoritesContextType {
  const store = useContext(FavoritesStoreContext);
  if (!store) throw new Error('useFavoritesContext must be used within FavoritesProvider');
  const state = useStore(store);
  // 只返回公开字段，排除内部字段
  return {
    favorites: state.favorites,
    favoritePendingIds: state.favoritePendingIds,
    favoriteTargets: state.favoriteTargets,
    favoriteTargetPendingKeys: state.favoriteTargetPendingKeys,
    topicCount: state.topicCount,
    favoriteTotal: state.favoriteTotal,
    sourceCount: state.sourceCount,
    todayPicksCount: state.todayPicksCount,
    reportContentTotal: state.reportContentTotal,
    reportTodayPicksTotal: state.reportTodayPicksTotal,
    isFavoriteTarget: state.isFavoriteTarget,
    toggleFavoriteTarget: state.toggleFavoriteTarget,
    toggleFavorite: state.toggleFavorite,
    refreshCounts: state.refreshCounts,
  };
}

// ── Provider ──────────────────────────────────────────────────

export function FavoritesProvider({
  children,
  initialCounts = null,
}: {
  children: React.ReactNode;
  initialCounts?: {
    todayPicks: number;
    sourceCount: number;
    favoriteTotal: number;
  } | null;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const authStore = useAuthStoreApi();

  // per-instance store
  const storeRef = useRef<FavoritesStore | null>(null);
  if (!storeRef.current) {
    storeRef.current = createFavoritesStore({
      authStore,
      router,
      initialCounts,
    });
  }
  const store = storeRef.current;

  // 读取 authLoading（用于控制初始化时机）
  const authLoading = useStore(authStore, (s) => s.authLoading);

  // 同步 pathname 到 store（refreshCounts 依赖它判断是否跳过 today-picks 计数）
  useEffect(() => {
    store.getState()._setPathname(pathname);
  }, [pathname, store]);

  // 主初始化 effect：登录/登出时加载或清空收藏
  useEffect(() => {
    if (authLoading) return;
    const currentUser = authStore.getState().currentUser;
    if (!currentUser) {
      store.getState()._clear();
      // 未登录用户仍需 today-picks 计数（侧边栏 badge），
      // 但 SSR 未预取时才走客户端拉取。
      if (!initialCounts) {
        void store.getState().refreshCounts();
      }
      return;
    }

    // 已登录：先从 localStorage 恢复（快速渲染），再从 API 校正
    store.getState()._loadFromStorage(currentUser.id);

    // SSR 已预取计数时，仅拉取完整收藏列表（更新 favorites Set / targetIds），
    // 跳过重复的计数请求。未预取时走原有 refreshCounts 全量拉取。
    if (initialCounts) {
      void store.getState()._loadFromIndex();
    } else {
      void store.getState().refreshCounts();
    }
  }, [authLoading, authStore, store, initialCounts]);

  return (
    <FavoritesStoreContext.Provider value={store}>
      {children}
    </FavoritesStoreContext.Provider>
  );
}

// Re-export types for backward compat
export type { FavoritesContextType };
