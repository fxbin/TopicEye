'use client';

import React, { createContext, useContext, useState, useCallback } from 'react';
import { ReaderDrawer } from '@/components/ReaderDrawer';

// ── Context type ──────────────────────────────────────────────

export interface ReaderContextType {
  /** 全局站内阅读抽屉：任意页面调用即可从右侧滑出正文（统一交互入口） */
  openReader: (contentId: number) => void;
}

const ReaderContext = createContext<ReaderContextType>({
  openReader: () => {},
});

export function useReaderContext() {
  return useContext(ReaderContext);
}

// ── Provider ──────────────────────────────────────────────────

export function ReaderProvider({ children }: { children: React.ReactNode }) {
  // 全局站内阅读抽屉：contentId 非空即打开、null 关闭；挂在根层，所有页面共用一个实例
  const [readerContentId, setReaderContentId] = useState<number | null>(null);

  const openReader = useCallback((contentId: number) => {
    setReaderContentId(contentId);
  }, []);

  return (
    <ReaderContext.Provider value={{ openReader }}>
      {children}
      {/* 全局站内阅读抽屉：所有页面统一从这里滑出，页面只需调用 openReader(contentId) */}
      <ReaderDrawer contentId={readerContentId} onClose={() => setReaderContentId(null)} />
    </ReaderContext.Provider>
  );
}
