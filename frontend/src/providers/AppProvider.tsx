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

// ── Backward-compatible hook: combines all three contexts ─────
// 38 个消费者继续用 useAppContext()，无需改动。

export function useAppContext(): AppContextType {
  const auth = useAuthContext();
  const favorites = useFavoritesContext();
  const reader = useReaderContext();
  return { ...auth, ...favorites, ...reader };
}

// Re-export individual hooks for new code that wants granular access
export { useAuthContext, useFavoritesContext, useReaderContext };
