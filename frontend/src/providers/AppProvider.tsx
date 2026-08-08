'use client';

import React from 'react';
import { AuthProvider, useAuthContext, type AuthContextType } from './AuthProvider';
import { FavoritesProvider, useFavoritesContext, type FavoritesContextType } from './FavoritesProvider';
import { ReaderProvider, useReaderContext, type ReaderContextType } from './ReaderProvider';
import type { PrefetchData } from '@/lib/server-prefetch';

// ── Combined type (backward compat with original AppContextType) ──

export type AppContextType = AuthContextType & FavoritesContextType & ReaderContextType;

// ── AppProvider: composes Auth → Favorites → Reader ───────────

export function AppProvider({ children, initialData }: { children: React.ReactNode; initialData: PrefetchData }) {
  return (
    <AuthProvider initialUser={initialData.user} initialFeatureFlags={initialData.featureFlags}>
      <FavoritesProvider initialCounts={initialData.counts}>
        <ReaderProvider>
          {children}
        </ReaderProvider>
      </FavoritesProvider>
    </AuthProvider>
  );
}

// ── Backward-compatible hook: combines all three stores ──────
// 38 个消费者继续用 useAppContext()，无需改动。
// 新代码推荐直接使用 useAuthStore / useFavoritesStore / useReaderStore
// 配合 selector 实现细粒度订阅，避免不必要 re-render。

export function useAppContext(): AppContextType {
  const auth = useAuthContext();
  const favorites = useFavoritesContext();
  const reader = useReaderContext();
  return { ...auth, ...favorites, ...reader };
}

// Re-export individual hooks for new code that wants granular access
export { useAuthContext, useFavoritesContext, useReaderContext };

// Re-export store hooks with selector support for new code
export { useAuthStore } from './AuthProvider';
export { useFavoritesStore } from './FavoritesProvider';
export { useReaderStore } from './ReaderProvider';
