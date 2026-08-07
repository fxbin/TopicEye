/**
 * Reader Store — 全局站内阅读抽屉状态。
 *
 * 使用 Zustand createStore（非 module-level create），
 * 由 ReaderProvider 通过 useRef 创建 per-instance store，
 * 保证 SSR 安全（每个请求独立 store，不跨请求泄漏）。
 */

import { createStore } from 'zustand';
import type { StoreApi } from 'zustand';

// ── State ─────────────────────────────────────────────────────

export interface ReaderState {
  /** 当前打开的内容 ID，null 表示关闭 */
  readerContentId: number | null;
  /** 打开阅读抽屉 */
  openReader: (contentId: number) => void;
  /** 关闭阅读抽屉 */
  closeReader: () => void;
}

export type ReaderStore = StoreApi<ReaderState>;

/** 向后兼容的 Context 类型（与原 ReaderContextType 一致） */
export type ReaderContextType = Pick<ReaderState, 'openReader'>;

// ── Factory ───────────────────────────────────────────────────

export function createReaderStore(): ReaderStore {
  return createStore<ReaderState>((set) => ({
    readerContentId: null,
    openReader: (contentId: number) => set({ readerContentId: contentId }),
    closeReader: () => set({ readerContentId: null }),
  }));
}
