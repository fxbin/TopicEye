'use client';

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { contentsApi, favoritesApi, sourcesApi } from '@/lib/api';
import {
  favoriteItemToTargetKey,
  getContentFavoriteKey,
  getFavoriteTargetKey,
  type FavoriteCreatePayload,
  type FavoriteTargetRef,
} from '@/lib/favorites';
import { isAdmin } from '@/lib/navigation';
import type { FavoriteItem } from '@/types';
import { useAuthContext } from './AuthProvider';

// ── Context type ──────────────────────────────────────────────

export interface FavoritesContextType {
  favorites: Set<number>;
  favoritePendingIds: Set<number>;
  favoriteTargets: Set<string>;
  favoriteTargetPendingKeys: Set<string>;
  topicCount: number;
  /** 侧边栏 badge 计数 */
  favoriteTotal: number;
  sourceCount: number;
  todayPicksCount: number;
  /** 首页等内容列表拿到 total 后回传，驱动侧边栏 badge 跟随时间筛选变化 */
  reportContentTotal: (total: number) => void;
  /** 当日精选页拿到自身 total 后回传，避免侧栏再并发请求一次同口径统计。 */
  reportTodayPicksTotal: (total: number) => void;
  isFavoriteTarget: (target: FavoriteTargetRef) => boolean;
  toggleFavoriteTarget: (target: FavoriteCreatePayload, options?: { throwOnError?: boolean }) => Promise<boolean>;
  toggleFavorite: (id: number, options?: { throwOnError?: boolean }) => Promise<boolean>;
  refreshCounts: () => void;
}

const FavoritesContext = createContext<FavoritesContextType>({
  favorites: new Set(),
  favoritePendingIds: new Set(),
  favoriteTargets: new Set(),
  favoriteTargetPendingKeys: new Set(),
  topicCount: 0,
  favoriteTotal: 0,
  sourceCount: 0,
  todayPicksCount: 0,
  reportContentTotal: () => {},
  reportTodayPicksTotal: () => {},
  isFavoriteTarget: () => false,
  toggleFavoriteTarget: async () => false,
  toggleFavorite: async () => false,
  refreshCounts: () => {},
});

export function useFavoritesContext() {
  return useContext(FavoritesContext);
}

// ── Helpers ───────────────────────────────────────────────────

const FAVORITES_STORAGE_KEY = 'topiceye_favorites';
const FAVORITE_TARGETS_STORAGE_KEY = 'topiceye_favorite_targets';
const FAVORITE_INDEX_PAGE_SIZE = 200;

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

// ── Provider ──────────────────────────────────────────────────

export function FavoritesProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { currentUser, authLoading } = useAuthContext();

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
    <FavoritesContext.Provider
      value={{
        favorites,
        favoritePendingIds,
        favoriteTargets,
        favoriteTargetPendingKeys,
        topicCount: contentCount,
        favoriteTotal,
        sourceCount,
        todayPicksCount,
        reportContentTotal: setContentCount,
        reportTodayPicksTotal: setTodayPicksCount,
        isFavoriteTarget,
        toggleFavoriteTarget,
        toggleFavorite,
        refreshCounts,
      }}
    >
      {children}
    </FavoritesContext.Provider>
  );
}


