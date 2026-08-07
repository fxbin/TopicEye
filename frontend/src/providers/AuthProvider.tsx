'use client';

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { authApi, getAuthToken, getAuthTokenExpiresAt, setAuthToken, setAuthTokenExpiresAt, settingsApi } from '@/lib/api';
import { canAccessPath, requiredAccessForPath } from '@/lib/navigation';
import type { AuthTokenResponse, AuthUser } from '@/types';

// ── Context type ──────────────────────────────────────────────

export interface AuthContextType {
  currentUser: AuthUser | null;
  authLoading: boolean;
  enabledFeatures: Record<string, boolean>;
  featuresLoading: boolean;
  applyAuthSession: (session: AuthTokenResponse) => void;
  updateEnabledFeatures: (flags: Record<string, boolean>) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  currentUser: null,
  authLoading: true,
  enabledFeatures: {},
  featuresLoading: true,
  applyAuthSession: () => {},
  updateEnabledFeatures: () => {},
  logout: async () => {},
});

export function useAuthContext() {
  return useContext(AuthContext);
}

// ── Provider ──────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [enabledFeatures, setEnabledFeatures] = useState<Record<string, boolean>>({});
  const [featuresLoading, setFeaturesLoading] = useState(true);

  const applyAuthSession = useCallback((session: AuthTokenResponse) => {
    setAuthToken(session.access_token);
    setAuthTokenExpiresAt(session.expires_at);
    setCurrentUser(session.user);
  }, []);

  const updateEnabledFeatures = useCallback((flags: Record<string, boolean>) => {
    setEnabledFeatures(flags || {});
  }, []);

  const logout = useCallback(async () => {
    try {
      if (getAuthToken()) {
        await authApi.logout();
      }
    } catch {
      // Local logout should still clear stale or invalid sessions.
    } finally {
      setAuthToken(null);
      setCurrentUser(null);
    }
  }, []);

  // 启动时校验 token、拉用户信息
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const token = getAuthToken();
      if (!token) {
        setAuthLoading(false);
        return;
      }
      try {
        // 启动时只在 session 即将过期时主动 refresh（剩余 < SESSION_REFRESH_THRESHOLD）。
        // 远未过期时跳过 refresh，直接拉 me()，减少一次网络请求。
        // refresh 失败（token 已过期超宽限期）不在此处登出，留给 me() 的
        // 401 拦截器处理。
        const expiresAtStr = getAuthTokenExpiresAt();
        const shouldRefresh = !expiresAtStr
          || new Date(expiresAtStr) < new Date(Date.now() + 7 * 86400000);
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
        if (!cancelled) setCurrentUser(user);
      } catch (err) {
        // 仅在 token 真正无效（401/403）时登出；
        // 网络错误（后端重启中）或 5xx 保留 token，避免热更新期间被误登出。
        const isAuthFail = err instanceof Error && (err as Error & { isAuthError?: boolean }).isAuthError;
        if (isAuthFail) {
          setAuthToken(null);
          if (!cancelled) setCurrentUser(null);
        }
      } finally {
        if (!cancelled) setAuthLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, []);

  // 拉取功能模块开关（管理员端点，普通用户 403 时回退空对象——所有 feature 视为关）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getAuthToken()) {
        setFeaturesLoading(false);
        return;
      }
      try {
        const { flags } = await settingsApi.getFeatureFlags();
        if (!cancelled) setEnabledFeatures(flags || {});
      } catch {
        // 非管理员或端点不可用：保持默认空对象（feature 全部视为关）
        if (!cancelled) setEnabledFeatures({});
      } finally {
        if (!cancelled) setFeaturesLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 路由守卫：feature 关闭或权限不足时踢回首页/登录
  useEffect(() => {
    if (authLoading || featuresLoading) return;
    if (canAccessPath(pathname, currentUser, enabledFeatures)) return;
    // feature 关闭的路径踢回首页（登录用户也可能命中）；权限不足按原有逻辑
    router.replace(requiredAccessForPath(pathname, enabledFeatures) === 'admin' && currentUser ? '/' : '/login');
  }, [authLoading, featuresLoading, currentUser, enabledFeatures, pathname, router]);

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        authLoading,
        enabledFeatures,
        featuresLoading,
        applyAuthSession,
        updateEnabledFeatures,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
