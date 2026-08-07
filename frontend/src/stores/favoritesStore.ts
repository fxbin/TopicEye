/**
 * Favorites Store — 收藏状态、侧边栏计数。
 *
 * 使用 Zustand createStore（非 module-level create），
 * 由 FavoritesProvider 通过 useRef 创建 per-instance store，
 * 保证 SSR 安全。
 *
 * 跨 store 依赖：通过 deps.authStore.getState() 读取 currentUser，
 * 不需要 React hooks，可在任意 action 中同步访问。
 *
 * 路由导航：通过 deps.router.push('/login') 实现未登录跳转，
 * router 由 Provider 注入（useRouter() 结果）。
 */

import { createStore } from 'zustand';
import type { StoreApi } from 'zustand';

import { contentsApi, favoritesApi, sourcesApi } from '@/lib/api';
import {
  favoriteItemToTargetKey,
  getContentFavoriteKey,
  getFavoriteTargetKey,
  type FavoriteCreatePayload,
  type FavoriteTargetRef,
} from '@/lib/favorites';
import { isAdmin } from '@/lib/navigation';
import type { AuthStore } from './authStore';

// ── Types ─────────────────────────────────────────────────────

export interface FavoritesState {
  // ── Public state (exposed via context) ──
  favorites: Set<number>;
  favoritePendingIds: Set<number>;
  favoriteTargets: Set<string>;
  favoriteTargetPendingKeys: Set<string>;
  /** 首页等内容列表 total 回传，驱动侧边栏 badge */
  topicCount: number;
  /** 侧边栏 badge 计数 */
  favoriteTotal: number;
  sourceCount: number;
  todayPicksCount: number;

  // ── Public actions ──
  reportContentTotal: (total: number) => void;
  reportTodayPicksTotal: (total: number) => void;
  isFavoriteTarget: (target: FavoriteTargetRef) => boolean;
  toggleFavoriteTarget: (
    target: FavoriteCreatePayload,
    options?: { throwOnError?: boolean },
  ) => Promise<boolean>;
  toggleFavorite: (id: number, options?: { throwOnError?: boolean }) => Promise<boolean>;
  refreshCounts: () => Promise<void>;

  // ── Internal state (not exposed via context type) ──
  /** target_key → favorite_id 映射，用于 toggle 时查找已收藏记录 */
  _favoriteTargetIds: Map<string, number>;
  /** 当前 pathname，refreshCounts 用它判断是否跳过 today-picks 计数 */
  _pathname: string;

  // ── Internal actions (called by Provider) ──
  _setPathname: (pathname: string) => void;
  /** 从 localStorage 加载收藏（登录后初始化） */
  _loadFromStorage: (userId: number) => void;
  /** 从 API /favorites/index 拉取收藏索引填充 Sets/Maps（SSR 已预取计数时使用） */
  _loadFromIndex: () => Promise<void>;
  /** 清空所有收藏状态（登出时使用） */
  _clear: () => void;
}

export type FavoritesStore = StoreApi<FavoritesState>;

/** 向后兼容的 Context 类型（与原 FavoritesContextType 一致） */
export type FavoritesContextType = Omit<
  FavoritesState,
  '_favoriteTargetIds' | '_pathname' | '_setPathname' | '_loadFromStorage' | '_loadFromIndex' | '_clear'
>;

// ── localStorage helpers ──────────────────────────────────────

const FAVORITES_STORAGE_KEY = 'topiceye_favorites';
const FAVORITE_TARGETS_STORAGE_KEY = 'topiceye_favorite_targets';

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

// ── Non-reactive pending guards ───────────────────────────────
// 模块级变量：同步防重入，不需要触发 re-render。
// 每次 createFavoritesStore 时重置，保证 per-instance 隔离。

let _favoritePending: Set<number> = new Set();
let _favoriteTargetPending: Set<string> = new Set();

// ── Factory ───────────────────────────────────────────────────

export function createFavoritesStore(deps: {
  authStore: AuthStore;
  router: { push: (path: string) => void };
  initialCounts?: { todayPicks: number; sourceCount: number; favoriteTotal: number } | null;
}): FavoritesStore {
  // 重置 pending guards for new store instance
  _favoritePending = new Set();
  _favoriteTargetPending = new Set();

  const { authStore, router, initialCounts } = deps;

  const store = createStore<FavoritesState>((set, get) => ({
    // ── Public state ──
    favorites: new Set(),
    favoritePendingIds: new Set(),
    favoriteTargets: new Set(),
    favoriteTargetPendingKeys: new Set(),
    topicCount: 0,
    favoriteTotal: initialCounts?.favoriteTotal ?? 0,
    sourceCount: initialCounts?.sourceCount ?? 0,
    todayPicksCount: initialCounts?.todayPicks ?? 0,

    // ── Public actions ──
    reportContentTotal: (total: number) => set({ topicCount: total }),
    reportTodayPicksTotal: (total: number) => set({ todayPicksCount: total }),

    isFavoriteTarget: (target: FavoriteTargetRef) => {
      try {
        return get().favoriteTargets.has(getFavoriteTargetKey(target));
      } catch {
        return false;
      }
    },

    refreshCounts: async () => {
      const { _pathname: pathname } = get();
      const currentUser = authStore.getState().currentUser;
      const isTodayPicksPage = pathname === '/today-picks';

      try {
        if (!currentUser) {
          if (!isTodayPicksPage) {
            const counts = await contentsApi.todayCount();
            set({ todayPicksCount: counts.today_picks || 0 });
          }
          set({
            sourceCount: 0,
            favoriteTotal: 0,
            favorites: new Set(),
            favoriteTargets: new Set(),
            _favoriteTargetIds: new Map(),
          });
          return;
        }
        const [counts, sources, favIndex] = await Promise.all([
          isTodayPicksPage ? Promise.resolve(null) : contentsApi.todayCount(),
          isAdmin(currentUser)
            ? sourcesApi.list({ page_size: 1 })
            : sourcesApi.listMine({ page_size: 1 }),
          favoritesApi.index(),
        ]);
        if (counts) set({ todayPicksCount: counts.today_picks || 0 });
        set({ sourceCount: sources ? sources.total || sources.items?.length || 0 : 0 });
        set({ favoriteTotal: favIndex.total || 0 });

        const targetKeys = new Set<string>();
        const targetIds = new Map<string, number>();
        const contentIds = new Set<number>();
        for (const item of favIndex.items || []) {
          const key = item.target_key;
          targetKeys.add(key);
          targetIds.set(key, item.id);
          if (item.target_type === 'content' && item.target_id) {
            contentIds.add(item.target_id);
          }
        }
        set({
          favoriteTargets: targetKeys,
          _favoriteTargetIds: targetIds,
          favorites: contentIds,
        });
      } catch {}
    },

    toggleFavoriteTarget: async (
      target: FavoriteCreatePayload,
      options?: { throwOnError?: boolean },
    ): Promise<boolean> => {
      const key = getFavoriteTargetKey(target);
      const currentUser = authStore.getState().currentUser;

      if (!currentUser) {
        router.push('/login');
        if (options?.throwOnError) {
          throw new Error('请先登录');
        }
        return get().favoriteTargets.has(key);
      }
      if (_favoriteTargetPending.has(key)) {
        return get().favoriteTargets.has(key);
      }

      const wasFavorited = get().favoriteTargets.has(key);
      _favoriteTargetPending.add(key);
      set((state) => ({
        favoriteTargetPendingKeys: new Set(state.favoriteTargetPendingKeys).add(key),
      }));

      try {
        if (wasFavorited) {
          let favoriteId = get()._favoriteTargetIds.get(key);
          if (!favoriteId) {
            const state = await favoritesApi.state({
              target_type: target.target_type,
              target_ids:
                target.target_id !== undefined && target.target_id !== null
                  ? [target.target_id]
                  : undefined,
              target_keys: target.target_key ? [target.target_key] : undefined,
            });
            favoriteId = state.items.find((item) => item.is_favorited)?.favorite_id || undefined;
          }
          if (!favoriteId) {
            throw new Error('收藏记录不存在，请刷新后重试');
          }
          await favoritesApi.delete(favoriteId);
          set((state) => {
            const newTargets = new Set(state.favoriteTargets);
            newTargets.delete(key);
            const newIds = new Map(state._favoriteTargetIds);
            newIds.delete(key);
            const newFavorites = new Set(state.favorites);
            if (target.target_type === 'content' && target.target_id) {
              newFavorites.delete(target.target_id as number);
            }
            return {
              favoriteTargets: newTargets,
              _favoriteTargetIds: newIds,
              favorites: newFavorites,
              favoriteTotal: Math.max(0, state.favoriteTotal - 1),
            };
          });
          return false;
        }

        const item = await favoritesApi.create(target);
        const itemKey = favoriteItemToTargetKey(item);
        set((state) => {
          const newTargets = new Set(state.favoriteTargets);
          newTargets.add(itemKey);
          const newIds = new Map(state._favoriteTargetIds);
          newIds.set(itemKey, item.id);
          const newFavorites = new Set(state.favorites);
          if (item.target_type === 'content' && item.target_id) {
            newFavorites.add(item.target_id as number);
          }
          return {
            favoriteTargets: newTargets,
            _favoriteTargetIds: newIds,
            favorites: newFavorites,
            favoriteTotal: state.favoriteTotal + 1,
          };
        });
        return true;
      } catch (err) {
        console.error('Toggle favorite target failed:', err);
        if (options?.throwOnError) {
          throw err;
        }
        return get().favoriteTargets.has(key);
      } finally {
        _favoriteTargetPending.delete(key);
        set((state) => {
          const next = new Set(state.favoriteTargetPendingKeys);
          next.delete(key);
          return { favoriteTargetPendingKeys: next };
        });
      }
    },

    toggleFavorite: async (
      id: number,
      options?: { throwOnError?: boolean },
    ): Promise<boolean> => {
      const targetKey = getContentFavoriteKey(id);
      const currentUser = authStore.getState().currentUser;

      if (!currentUser) {
        router.push('/login');
        if (options?.throwOnError) {
          throw new Error('请先登录');
        }
        return get().favorites.has(id);
      }
      if (_favoritePending.has(id)) {
        return get().favorites.has(id);
      }

      const wasFavorited = get().favorites.has(id);
      _favoritePending.add(id);
      set((state) => ({
        favoritePendingIds: new Set(state.favoritePendingIds).add(id),
      }));

      try {
        const result = await contentsApi.toggleFavorite(id);
        set((state) => {
          const newFavorites = new Set(state.favorites);
          if (result.is_favorited) {
            newFavorites.add(id);
          } else {
            newFavorites.delete(id);
          }
          const newTargets = new Set(state.favoriteTargets);
          if (result.is_favorited) {
            newTargets.add(targetKey);
          } else {
            newTargets.delete(targetKey);
          }
          const newIds = new Map(state._favoriteTargetIds);
          if (result.is_favorited && result.favorite_id) {
            newIds.set(targetKey, result.favorite_id);
          } else {
            newIds.delete(targetKey);
          }
          const newTotal =
            result.is_favorited !== wasFavorited
              ? Math.max(0, state.favoriteTotal + (result.is_favorited ? 1 : -1))
              : state.favoriteTotal;
          return {
            favorites: newFavorites,
            favoriteTargets: newTargets,
            _favoriteTargetIds: newIds,
            favoriteTotal: newTotal,
          };
        });
        return result.is_favorited;
      } catch (err) {
        console.error('Toggle favorite failed:', err);
        if (options?.throwOnError) {
          throw err;
        }
        return get().favorites.has(id);
      } finally {
        _favoritePending.delete(id);
        set((state) => {
          const next = new Set(state.favoritePendingIds);
          next.delete(id);
          return { favoritePendingIds: next };
        });
      }
    },

    // ── Internal actions ──
    _setPathname: (pathname: string) => set({ _pathname: pathname }),

    _loadFromStorage: (userId: number) => {
      const storedFavorites = loadFavoritesFromStorage(userId);
      const storedFavoriteTargets = loadFavoriteTargetsFromStorage(userId);
      for (const id of storedFavorites) {
        storedFavoriteTargets.add(getContentFavoriteKey(id));
      }
      set({
        favorites: storedFavorites,
        favoriteTargets: storedFavoriteTargets,
        _favoriteTargetIds: new Map(),
      });
    },

    _loadFromIndex: async () => {
      try {
        const favIndex = await favoritesApi.index();
        const targetKeys = new Set<string>();
        const targetIds = new Map<string, number>();
        const contentIds = new Set<number>();
        for (const item of favIndex.items || []) {
          const key = item.target_key;
          targetKeys.add(key);
          targetIds.set(key, item.id);
          if (item.target_type === 'content' && item.target_id) {
            contentIds.add(item.target_id as number);
          }
        }
        set({
          favoriteTargets: targetKeys,
          _favoriteTargetIds: targetIds,
          favorites: contentIds,
          // 用服务端返回的精确 total 校正 SSR 预取值
          favoriteTotal: favIndex.total || 0,
        });
      } catch {
        // 静默失败，保留 SSR 预取的初始值
      }
    },

    _clear: () => {
      set({
        favorites: new Set(),
        favoriteTargets: new Set(),
        _favoriteTargetIds: new Map(),
        favoriteTotal: 0,
      });
    },

    // ── Internal state ──
    _favoriteTargetIds: new Map(),
    _pathname: '/',
  }));

  // ── localStorage sync: subscribe to state changes ───────────
  // 封装在 store 创建时，Provider 不需要额外处理。
  store.subscribe((state, prevState) => {
    const userId = authStore.getState().currentUser?.id || null;
    if (state.favorites !== prevState.favorites) {
      saveFavoritesToStorage(userId, state.favorites);
    }
    if (state.favoriteTargets !== prevState.favoriteTargets) {
      saveFavoriteTargetsToStorage(userId, state.favoriteTargets);
    }
  });

  return store;
}
