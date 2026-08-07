/**
 * Auth Store — 用户认证、功能开关状态。
 *
 * 使用 Zustand createStore（非 module-level create），
 * 由 AuthProvider 通过 useRef 创建 per-instance store，
 * 保证 SSR 安全（每个请求独立 store，不跨请求泄漏）。
 *
 * 复杂副作用（token 校验、feature flags 拉取、路由守卫）
 * 留在 AuthProvider 组件中，store 只持有状态 + 纯 setter/action。
 */

import { createStore } from 'zustand';
import type { StoreApi } from 'zustand';

import {
  authApi,
  getAuthToken,
  getAuthTokenExpiresAt,
  setAuthToken,
  setAuthTokenExpiresAt,
} from '@/lib/api';
import type { AuthTokenResponse, AuthUser } from '@/types';

// ── State ─────────────────────────────────────────────────────

export interface AuthState {
  currentUser: AuthUser | null;
  authLoading: boolean;
  enabledFeatures: Record<string, boolean>;
  featuresLoading: boolean;
  /** 登录成功后写入 token + 用户 */
  applyAuthSession: (session: AuthTokenResponse) => void;
  /** 更新功能开关 */
  updateEnabledFeatures: (flags: Record<string, boolean>) => void;
  /** 登出（调后端 revoke + 清本地 token） */
  logout: () => Promise<void>;
}

export type AuthStore = StoreApi<AuthState>;

/** 向后兼容的 Context 类型（与原 AuthContextType 一致） */
export type AuthContextType = AuthState;

// ── Factory ───────────────────────────────────────────────────

export function createAuthStore(initial: {
  user: AuthUser | null;
  featureFlags?: Record<string, boolean>;
}): AuthStore {
  return createStore<AuthState>((set) => ({
    currentUser: initial.user,
    // SSR 预取已返回用户信息时跳过 authLoading 白屏阶段
    authLoading: !initial.user,
    enabledFeatures: initial.featureFlags ?? {},
    featuresLoading: !initial.featureFlags,

    applyAuthSession: (session: AuthTokenResponse) => {
      setAuthToken(session.access_token);
      setAuthTokenExpiresAt(session.expires_at);
      set({ currentUser: session.user });
    },

    updateEnabledFeatures: (flags: Record<string, boolean>) => {
      set({ enabledFeatures: flags || {} });
    },

    logout: async () => {
      try {
        if (getAuthToken()) {
          await authApi.logout();
        }
      } catch {
        // Local logout should still clear stale or invalid sessions.
      } finally {
        setAuthToken(null);
        set({ currentUser: null });
      }
    },
  }));
}

// ── Convenience: read auth state outside React ────────────────

/**
 * 从 AuthStore 读取 currentUser（非响应式，用于跨 store 同步读取）。
 * 必须在 AuthProvider 挂载后调用。
 */
export function getCurrentUser(authStore: AuthStore): AuthUser | null {
  return authStore.getState().currentUser;
}
