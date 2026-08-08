'use client';

import React, { createContext, useContext, useRef } from 'react';
import { useStore } from 'zustand';
import { ReaderDrawer } from '@/components/ReaderDrawer';
import {
  createReaderStore,
  type ReaderStore,
  type ReaderState,
  type ReaderContextType,
} from '@/stores/readerStore';

// ── Context: holds the per-instance store ─────────────────────

const ReaderStoreContext = createContext<ReaderStore | null>(null);

// ── Hooks ─────────────────────────────────────────────────────

/**
 * 细粒度 selector hook（新代码推荐使用）。
 *
 * @example
 * const openReader = useReaderStore(s => s.openReader);
 */
export function useReaderStore<T>(selector: (s: ReaderState) => T): T {
  const store = useContext(ReaderStoreContext);
  if (!store) throw new Error('useReaderStore must be used within ReaderProvider');
  return useStore(store, selector);
}

/** 向后兼容 hook（与原 useContext(ReaderContext) 行为一致） */
export function useReaderContext(): ReaderContextType {
  const store = useContext(ReaderStoreContext);
  if (!store) throw new Error('useReaderContext must be used within ReaderProvider');
  return useStore(store, (s) => ({ openReader: s.openReader }));
}

// ── Provider ──────────────────────────────────────────────────

export function ReaderProvider({ children }: { children: React.ReactNode }) {
  // per-instance store
  const storeRef = useRef<ReaderStore | null>(null);
  if (!storeRef.current) {
    storeRef.current = createReaderStore();
  }
  const store = storeRef.current;

  // ReaderDrawer 只需要 readerContentId 和 closeReader
  const readerContentId = useStore(store, (s) => s.readerContentId);
  const closeReader = useStore(store, (s) => s.closeReader);

  return (
    <ReaderStoreContext.Provider value={store}>
      {children}
      {/* 全局站内阅读抽屉：所有页面统一从这里滑出，页面只需调用 openReader(contentId) */}
      <ReaderDrawer contentId={readerContentId} onClose={closeReader} />
    </ReaderStoreContext.Provider>
  );
}

// Re-export types for backward compat
export type { ReaderContextType };
