'use client';

import React, { createContext, useContext, useEffect, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useStore } from 'zustand';
import { getAuthToken, getAuthTokenExpiresAt, setAuthToken, setAuthTokenExpiresAt, authApi, settingsApi } from '@/lib/api';
import { canAccessPath, requiredAccessForPath } from '@/lib/navigation';
import type { AuthUser } from '@/types';
import { createAuthStore, type AuthStore, type AuthState, type AuthContextType } from '@/stores/authStore';

// ── Context: holds the per-instance store ─────────────────────

const AuthStoreContext = createContext<AuthStore | null>(null);

// ── Hooks ─────────────────────────────────────────────────────

/**
 * 细粒度 selector hook（新代码推荐使用）。
 * 只在选中的 state slice 变化时 re-render。
 *
 * @example
 * const currentUser = useAuthStore(s => s.currentUser);
 * const logout = useAuthStore(s => s.logout);
 */
export function useAuthStore<T>(selector: (s: AuthState) => T): T {
  const store = useContext(AuthStoreContext);
  if (!store) throw new Error('useAuthStore must be used within AuthProvider');
  return useStore(store, selector);
}

/**
 * 向后兼容 hook：订阅整个 auth store（与原 useContext(AuthContext) 行为一致）。
 * 38 个现有消费者通过 useAppContext() 间接使用，无需改动。
 */
export function useAuthContext(): AuthContextType {
  const store = useContext(AuthStoreContext);
  if (!store) throw new Error('useAuthContext must be used within AuthProvider');
  return useStore(store);
}

/**
 * 获取 AuthStore 实例（非响应式，用于跨 store 依赖注入）。
 * 仅在 Provider 内部使用。
 */
export function useAuthStoreApi(): AuthStore {
  const store = useContext(AuthStoreContext);
  if (!store) throw new Error('useAuthStoreApi must be used within AuthProvider');
  return store;
}

// ── Provider ──────────────────────────────────────────────────

export function AuthProvider({
  children,
  initialUser = null,
  initialFeatureFlags,
}: {
  children: React.ReactNode;
  initialUser?: AuthUser | null;
  initialFeatureFlags?: Record<string, boolean>;
}) {
  const router = useRouter();
  const pathname = usePathname();

  // per-instance store（useRef 保证 SSR 安全：每个请求/组件实例独立 store）
  const storeRef = useRef<AuthStore | null>(null);
  if (!storeRef.current) {
    storeRef.current = createAuthStore({
      user: initialUser,
      featureFlags: initialFeatureFlags,
    });
  }
  const store = storeRef.current;

  // 读取响应式 state（用于路由守卫 effect）
  const authLoading = useStore(store, (s) => s.authLoading);
  const featuresLoading = useStore(store, (s) => s.featuresLoading);
  const currentUser = useStore(store, (s) => s.currentUser);
  const enabledFeatures = useStore(store, (s) => s.enabledFeatures);

  // 启动时校验 token、拉用户信息
  // SSR 预取已返回用户信息时跳过此 useEffect，避免重复请求。
  useEffect(() => {
    if (initialUser) return; // SSR 已预取，跳过
    let cancelled = false;

    (async () => {
      const token = getAuthToken();
      if (!token) {
        store.setState({ authLoading: false });
        return;
      }
      try {
        // 启动时只在 session 即将过期时主动 refresh（剩余 < SESSION_REFRESH_THRESHOLD）。
        const expiresAtStr = getAuthTokenExpiresAt();
        const shouldRefresh =
          !expiresAtStr || new Date(expiresAtStr) < new Date(Date.now() + 7 * 86400000);
        if (shouldRefresh) {
          try {
            const refreshed = await authApi.refresh();
            if (!cancelled) {
              setAuthTokenExpiresAt(refreshed.expires_at);
            }
          } catch {
            // refresh 失败不阻塞——继续走 me()，me() 的 401 拦截器会再试一次
          }
        }
        const user = await authApi.me();
        if (!cancelled) store.setState({ currentUser: user });
      } catch (err) {
        // 仅在 token 真正无效（401/403）时登出；
        // 网络错误（后端重启中）或 5xx 保留 token，避免热更新期间被误登出。
        const isAuthFail =
          err instanceof Error && (err as Error & { isAuthError?: boolean }).isAuthError;
        if (isAuthFail) {
          // Token 无效（401/403）→ 清本地 token，不调后端 logout（也会失败）
          setAuthToken(null);
          if (!cancelled) store.setState({ currentUser: null });
        }
      } finally {
        if (!cancelled) store.setState({ authLoading: false });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [store, initialUser]);

  // 拉取功能模块开关（管理员端点，普通用户 403 时回退空对象）
  // SSR 预取已返回 feature flags 时跳过此 useEffect。
  useEffect(() => {
    if (initialFeatureFlags) return; // SSR 已预取，跳过
    let cancelled = false;
    (async () => {
      if (!getAuthToken()) {
        store.setState({ featuresLoading: false });
        return;
      }
      try {
        const { flags } = await settingsApi.getFeatureFlags();
        if (!cancelled) store.setState({ enabledFeatures: flags || {} });
      } catch {
        // 非管理员或端点不可用：保持默认空对象（feature 全部视为关）
        if (!cancelled) store.setState({ enabledFeatures: {} });
      } finally {
        if (!cancelled) store.setState({ featuresLoading: false });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [store, initialFeatureFlags]);

  // 路由守卫：feature 关闭或权限不足时踢回首页/登录
  useEffect(() => {
    if (authLoading || featuresLoading) return;
    if (canAccessPath(pathname, currentUser, enabledFeatures)) return;
    router.replace(
      requiredAccessForPath(pathname, enabledFeatures) === 'admin' && currentUser
        ? '/'
        : '/login',
    );
  }, [authLoading, featuresLoading, currentUser, enabledFeatures, pathname, router]);

  return <AuthStoreContext.Provider value={store}>{children}</AuthStoreContext.Provider>;
}

// Re-export types for backward compat
export type { AuthContextType };
