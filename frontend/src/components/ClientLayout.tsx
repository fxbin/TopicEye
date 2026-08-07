'use client';

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Sidebar from '@/components/Sidebar';
import NotificationBell from '@/components/NotificationBell';
import { authApi, getAuthToken, getAuthTokenExpiresAt, setAuthToken, setAuthTokenExpiresAt, settingsApi, sourcesApi, contentsApi, favoritesApi } from '@/lib/api';
import {
  favoriteItemToTargetKey,
  getContentFavoriteKey,
  getFavoriteTargetKey,
  type FavoriteCreatePayload,
  type FavoriteTargetRef,
} from '@/lib/favorites';
import { canAccessPath, isAdmin, requiredAccessForPath } from '@/lib/navigation';
import { ReaderDrawer } from '@/components/ReaderDrawer';
import type { AuthTokenResponse, AuthUser, FavoriteItem } from '@/types';

// App context - shared across pages
interface AppContextType {
  currentUser: AuthUser | null;
  authLoading: boolean;
  enabledFeatures: Record<string, boolean>;
  featuresLoading: boolean;
  favorites: Set<number>;
  favoritePendingIds: Set<number>;
  favoriteTargets: Set<string>;
  favoriteTargetPendingKeys: Set<string>;
  topicCount: number;
  /** 首页等内容列表拿到 total 后回传，驱动侧边栏 badge 跟随时间筛选变化 */
  reportContentTotal: (total: number) => void;
  /** 当日精选页拿到自身 total 后回传，避免侧栏再并发请求一次同口径统计。 */
  reportTodayPicksTotal: (total: number) => void;
  isFavoriteTarget: (target: FavoriteTargetRef) => boolean;
  applyAuthSession: (session: AuthTokenResponse) => void;
  /** 同步更新 enabledFeatures（toggle 后调用，菜单/路由守卫实时刷新） */
  updateEnabledFeatures: (flags: Record<string, boolean>) => void;
  logout: () => Promise<void>;
  toggleFavoriteTarget: (target: FavoriteCreatePayload, options?: { throwOnError?: boolean }) => Promise<boolean>;
  toggleFavorite: (id: number, options?: { throwOnError?: boolean }) => Promise<boolean>;
  refreshCounts: () => void;
  /** 全局站内阅读抽屉：任意页面调用即可从右侧滑出正文（统一交互入口） */
  openReader: (contentId: number) => void;
}

const AppContext = createContext<AppContextType>({
  currentUser: null,
  authLoading: true,
  enabledFeatures: {},
  featuresLoading: true,
  favorites: new Set(),
  favoritePendingIds: new Set(),
  favoriteTargets: new Set(),
  favoriteTargetPendingKeys: new Set(),
  topicCount: 0,
  reportContentTotal: () => {},
  reportTodayPicksTotal: () => {},
  isFavoriteTarget: () => false,
  applyAuthSession: () => {},
  updateEnabledFeatures: () => {},
  logout: async () => {},
  toggleFavoriteTarget: async () => false,
  toggleFavorite: async () => false,
  refreshCounts: () => {},
  openReader: () => {},
});

export function useAppContext() {
  return useContext(AppContext);
}

const FAVORITES_STORAGE_KEY = 'topiceye_favorites';
const FAVORITE_TARGETS_STORAGE_KEY = 'topiceye_favorite_targets';
const FAVORITE_INDEX_PAGE_SIZE = 200;
const CHROMELESS_PATHS = new Set(['/login']);
const ADMIN_PATH_PREFIX = '/admin';

function userStorageKey(baseKey: string, userId: number | null): string {
  return userId ? `${baseKey}:user:${userId}` : baseKey;
}

function loadFavoritesFromStorage(userId: number | null): Set<number> {
  if (!userId) return new Set();
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = localStorage.getItem(userStorageKey(FAVORITES_STORAGE_KEY, userId));
    if (!raw) return new Set();
    const arr: number[] = JSON.parse(raw);
    return new Set(arr);
  } catch {
    return new Set();
  }
}

function loadFavoriteTargetsFromStorage(userId: number | null): Set<string> {
  if (!userId) return new Set();
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = localStorage.getItem(userStorageKey(FAVORITE_TARGETS_STORAGE_KEY, userId));
    if (!raw) return new Set();
    const arr: string[] = JSON.parse(raw);
    return new Set(arr.filter((item) => typeof item === 'string' && item.includes(':')));
  } catch {
    return new Set();
  }
}

function saveFavoritesToStorage(userId: number | null, favSet: Set<number>): void {
  if (!userId) return;
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(userStorageKey(FAVORITES_STORAGE_KEY, userId), JSON.stringify([...favSet]));
  } catch {}
}

function saveFavoriteTargetsToStorage(userId: number | null, favSet: Set<string>): void {
  if (!userId) return;
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(userStorageKey(FAVORITE_TARGETS_STORAGE_KEY, userId), JSON.stringify([...favSet]));
  } catch {}
}

async function fetchAllFavoriteItems(): Promise<{ items: FavoriteItem[]; total: number }> {
  const firstPage = await favoritesApi.list({ page: 1, page_size: FAVORITE_INDEX_PAGE_SIZE });
  const total = firstPage.total || 0;
  const items = [...(firstPage.items || [])];
  const totalPages = Math.ceil(total / FAVORITE_INDEX_PAGE_SIZE);

  if (totalPages <= 1) {
    return { items, total };
  }

  const remainingPages = await Promise.all(
    Array.from({ length: totalPages - 1 }, (_, index) => (
      favoritesApi.list({ page: index + 2, page_size: FAVORITE_INDEX_PAGE_SIZE })
    ))
  );
  for (const page of remainingPages) {
    items.push(...(page.items || []));
  }
  return { items, total };
}

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [enabledFeatures, setEnabledFeatures] = useState<Record<string, boolean>>({});
  const [featuresLoading, setFeaturesLoading] = useState(true);
  const [favorites, setFavorites] = useState<Set<number>>(new Set());
  const [favoritePendingIds, setFavoritePendingIds] = useState<Set<number>>(new Set());
  const favoritePendingRef = useRef<Set<number>>(new Set());
  const [favoriteTargets, setFavoriteTargets] = useState<Set<string>>(new Set());
  const [favoriteTargetIds, setFavoriteTargetIds] = useState<Map<string, number>>(new Map());
  const [favoriteTargetPendingKeys, setFavoriteTargetPendingKeys] = useState<Set<string>>(new Set());
  const favoriteTargetPendingRef = useRef<Set<string>>(new Set());
  const [contentCount, setContentCount] = useState(0);
  const [sourceCount, setSourceCount] = useState(0);
  const [favoriteTotal, setFavoriteTotal] = useState(0);
  const [todayPicksCount, setTodayPicksCount] = useState(0);
  const [compactNav, setCompactNav] = useState(false);
  // 全局站内阅读抽屉：contentId 非空即打开、null 关闭；挂在根层，所有页面共用一个实例
  const [readerContentId, setReaderContentId] = useState<number | null>(null);
  const isChromelessPath = CHROMELESS_PATHS.has(pathname);
  const isAdminPath = pathname === ADMIN_PATH_PREFIX || pathname.startsWith(`${ADMIN_PATH_PREFIX}/`);

  const applyAuthSession = useCallback((session: AuthTokenResponse) => {
    setAuthToken(session.access_token);
    setAuthTokenExpiresAt(session.expires_at);
    setCurrentUser(session.user);
  }, []);

  const openReader = useCallback((contentId: number) => {
    setReaderContentId(contentId);
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

  const refreshCounts = useCallback(async () => {
    try {
      // 当前页面会自行获取同口径的精选 total；跳过侧栏的重复重算，避免冷启动时
      // 两个 DuckDB 全量评分查询互相阻塞首屏。
      const isTodayPicksPage = pathname === '/today-picks';
      if (!currentUser) {
        if (!isTodayPicksPage) {
          const counts = await contentsApi.todayCount();
          setTodayPicksCount(counts.today_picks || 0);
        }
        setSourceCount(0);
        setFavoriteTotal(0);
        setFavorites(new Set());
        setFavoriteTargets(new Set());
        setFavoriteTargetIds(new Map());
        return;
      }
      const [counts, sources, allFavorites] = await Promise.all([
        isTodayPicksPage ? Promise.resolve(null) : contentsApi.todayCount(),
        isAdmin(currentUser)
          ? sourcesApi.list({ page_size: 1 })
          : sourcesApi.listMine({ page_size: 1 }),
        fetchAllFavoriteItems(),
      ]);
      if (counts) setTodayPicksCount(counts.today_picks || 0);
      setSourceCount(sources ? sources.total || sources.items?.length || 0 : 0);
      setFavoriteTotal(allFavorites.total || 0);

      const targetKeys = new Set<string>();
      const targetIds = new Map<string, number>();
      const contentIds = new Set<number>();
      for (const item of allFavorites.items || []) {
        const key = favoriteItemToTargetKey(item);
        targetKeys.add(key);
        targetIds.set(key, item.id);
        if (item.target_type === 'content' && item.target_id) {
          contentIds.add(item.target_id);
        }
      }
      setFavoriteTargets(targetKeys);
      setFavoriteTargetIds(targetIds);
      setFavorites(contentIds);
    } catch {}
  }, [currentUser, pathname]);

  useEffect(() => {
    if (authLoading) return;
    if (!currentUser) {
      setFavorites(new Set());
      setFavoriteTargets(new Set());
      setFavoriteTargetIds(new Map());
      setFavoriteTotal(0);
      void refreshCounts();
      return;
    }

    const storedFavorites = loadFavoritesFromStorage(currentUser.id);
    setFavorites(storedFavorites);
    const storedFavoriteTargets = loadFavoriteTargetsFromStorage(currentUser.id);
    for (const id of storedFavorites) {
      storedFavoriteTargets.add(getContentFavoriteKey(id));
    }
    setFavoriteTargets(storedFavoriteTargets);
    setFavoriteTargetIds(new Map());
    void refreshCounts();
  }, [authLoading, currentUser, refreshCounts]);

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

  useEffect(() => {
    const updateCompact = () => setCompactNav(window.innerWidth < 900);
    updateCompact();
    window.addEventListener('resize', updateCompact);
    return () => window.removeEventListener('resize', updateCompact);
  }, []);

  useEffect(() => {
    if (authLoading || featuresLoading) return;
    if (canAccessPath(pathname, currentUser, enabledFeatures)) return;
    // feature 关闭的路径踢回首页（登录用户也可能命中）；权限不足按原有逻辑
    router.replace(requiredAccessForPath(pathname, enabledFeatures) === 'admin' && currentUser ? '/' : '/login');
  }, [authLoading, featuresLoading, currentUser, enabledFeatures, pathname, router]);

  // Sync favorites to localStorage whenever it changes
  useEffect(() => {
    saveFavoritesToStorage(currentUser?.id || null, favorites);
  }, [currentUser?.id, favorites]);

  useEffect(() => {
    saveFavoriteTargetsToStorage(currentUser?.id || null, favoriteTargets);
  }, [currentUser?.id, favoriteTargets]);

  const isFavoriteTarget = useCallback((target: FavoriteTargetRef): boolean => {
    try {
      return favoriteTargets.has(getFavoriteTargetKey(target));
    } catch {
      return false;
    }
  }, [favoriteTargets]);

  const toggleFavoriteTarget = useCallback(async (
    target: FavoriteCreatePayload,
    options?: { throwOnError?: boolean },
  ): Promise<boolean> => {
    const key = getFavoriteTargetKey(target);
    if (!currentUser) {
      router.push('/login');
      if (options?.throwOnError) {
        throw new Error('请先登录');
      }
      return favoriteTargets.has(key);
    }
    if (favoriteTargetPendingRef.current.has(key)) {
      return favoriteTargets.has(key);
    }

    const wasFavorited = favoriteTargets.has(key);
    favoriteTargetPendingRef.current.add(key);
    setFavoriteTargetPendingKeys((prev) => new Set(prev).add(key));

    try {
      if (wasFavorited) {
        let favoriteId = favoriteTargetIds.get(key);
        if (!favoriteId) {
          const state = await favoritesApi.state({
            target_type: target.target_type,
            target_ids: target.target_id !== undefined && target.target_id !== null ? [target.target_id] : undefined,
            target_keys: target.target_key ? [target.target_key] : undefined,
          });
          favoriteId = state.items.find((item) => item.is_favorited)?.favorite_id || undefined;
        }
        if (!favoriteId) {
          throw new Error('收藏记录不存在，请刷新后重试');
        }
        await favoritesApi.delete(favoriteId);
        setFavoriteTargets((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
        setFavoriteTargetIds((prev) => {
          const next = new Map(prev);
          next.delete(key);
          return next;
        });
        if (target.target_type === 'content' && target.target_id) {
          setFavorites((prev) => {
            const next = new Set(prev);
            next.delete(target.target_id as number);
            return next;
          });
        }
        setFavoriteTotal((prev) => Math.max(0, prev - 1));
        return false;
      }

      const item = await favoritesApi.create(target);
      const itemKey = favoriteItemToTargetKey(item);
      setFavoriteTargets((prev) => new Set(prev).add(itemKey));
      setFavoriteTargetIds((prev) => new Map(prev).set(itemKey, item.id));
      if (item.target_type === 'content' && item.target_id) {
        setFavorites((prev) => new Set(prev).add(item.target_id as number));
      }
      setFavoriteTotal((prev) => prev + 1);
      return true;
    } catch (err) {
      console.error('Toggle favorite target failed:', err);
      if (options?.throwOnError) {
        throw err;
      }
      return favoriteTargets.has(key);
    } finally {
      favoriteTargetPendingRef.current.delete(key);
      setFavoriteTargetPendingKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  }, [currentUser, favoriteTargetIds, favoriteTargets, router]);

  const toggleFavorite = useCallback(async (id: number, options?: { throwOnError?: boolean }): Promise<boolean> => {
    const targetKey = getContentFavoriteKey(id);
    if (!currentUser) {
      router.push('/login');
      if (options?.throwOnError) {
        throw new Error('请先登录');
      }
      return favorites.has(id);
    }
    if (favoritePendingRef.current.has(id)) {
      return favorites.has(id);
    }
    const wasFavorited = favorites.has(id);
    favoritePendingRef.current.add(id);
    setFavoritePendingIds((prev) => new Set(prev).add(id));
    try {
      const result = await contentsApi.toggleFavorite(id);
      setFavorites((prev) => {
        const next = new Set(prev);
        if (result.is_favorited) {
          next.add(id);
        } else {
          next.delete(id);
        }
        return next;
      });
      setFavoriteTargets((prev) => {
        const next = new Set(prev);
        if (result.is_favorited) {
          next.add(targetKey);
        } else {
          next.delete(targetKey);
        }
        return next;
      });
      setFavoriteTargetIds((prev) => {
        const next = new Map(prev);
        if (result.is_favorited && result.favorite_id) {
          next.set(targetKey, result.favorite_id);
        } else {
          next.delete(targetKey);
        }
        return next;
      });
      if (result.is_favorited !== wasFavorited) {
        setFavoriteTotal((prev) => Math.max(0, prev + (result.is_favorited ? 1 : -1)));
      }
      return result.is_favorited;
    } catch (err) {
      console.error('Toggle favorite failed:', err);
      if (options?.throwOnError) {
        throw err;
      }
      return favorites.has(id);
    } finally {
      favoritePendingRef.current.delete(id);
      setFavoritePendingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }, [currentUser, favorites, router]);

  return (
    <AppContext.Provider
      value={{
        currentUser,
        authLoading,
        enabledFeatures,
        featuresLoading,
        favorites,
        favoritePendingIds,
        favoriteTargets,
        favoriteTargetPendingKeys,
        topicCount: contentCount,
        reportContentTotal: setContentCount,
        reportTodayPicksTotal: setTodayPicksCount,
        isFavoriteTarget,
        applyAuthSession,
        updateEnabledFeatures,
        logout,
        toggleFavoriteTarget,
        toggleFavorite,
        refreshCounts,
        openReader,
      }}
    >
      {isChromelessPath ? (
        <main className="h-dvh overflow-hidden bg-page">
          {children}
        </main>
      ) : isAdminPath ? (
        // admin 路径由 app/admin/layout.tsx 接管壳，这里只保留 AppContext
        <main className="h-dvh overflow-hidden bg-page">
          {children}
        </main>
      ) : (
        <div className="flex h-dvh overflow-hidden">
          <Sidebar
            topicCount={contentCount}
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
      )}
      {/* 全局站内阅读抽屉：所有页面统一从这里滑出，页面只需调用 openReader(contentId) */}
      <ReaderDrawer contentId={readerContentId} onClose={() => setReaderContentId(null)} />
    </AppContext.Provider>
  );
}
