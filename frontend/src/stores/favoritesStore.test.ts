import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createAuthStore } from './authStore';
import { createFavoritesStore } from './favoritesStore';
import { contentsApi, favoritesApi, sourcesApi } from '@/lib/api';
import type { AuthUser } from '@/types';

vi.mock('@/lib/api', () => ({
  contentsApi: { todayCount: vi.fn(), toggleFavorite: vi.fn() },
  favoritesApi: { index: vi.fn(), state: vi.fn(), create: vi.fn(), delete: vi.fn() },
  sourcesApi: { list: vi.fn(), listMine: vi.fn() },
}));
const user = (id: number) => ({ id, role: 'user', email: `${id}@test` }) as AuthUser;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const index = (id = 41) => ({ items: [{ id: 101, target_type: 'content' as const, target_id: id, target_key: `content:${id}` }], total: 1 });
function fixture() {
  const auth = createAuthStore({ user: user(1) });
  const store = createFavoritesStore({ authStore: auth, router: { push: vi.fn() } });
  return { auth, store };
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(contentsApi.todayCount).mockResolvedValue({ today_picks: 20, today_content: 50 });
  vi.mocked(sourcesApi.listMine).mockResolvedValue({ total: 4, items: [] } as never);
});

describe('收藏异步结果的账号归属', () => {
  it('同一账号首次恢复收藏时保留SSR计数', () => {
    const auth = createAuthStore({ user: user(1) });
    const store = createFavoritesStore({ authStore: auth, router: { push: vi.fn() }, initialCounts: { todayPicks: 20, sourceCount: 4, favoriteTotal: 3 } });
    store.getState()._loadFromStorage(1);
    expect(store.getState().todayPicksCount).toBe(20);
    expect(store.getState().sourceCount).toBe(4);
    expect(store.getState().favoriteTotal).toBe(3);
  });
  it.each(['logout', 'switch'] as const)('精选页%s清零后重新取得当前账号计数', async (transition) => {
    const { auth, store } = fixture();
    store.getState()._setPathname('/today-picks');
    store.getState().reportTodayPicksTotal(37);
    if (transition === 'logout') {
      auth.setState({ currentUser: null });
      store.getState()._clear();
    } else {
      auth.setState({ currentUser: user(2) });
      store.getState()._loadFromStorage(2);
      vi.mocked(favoritesApi.index).mockResolvedValueOnce(index(42));
    }
    await store.getState().refreshCounts();
    expect(contentsApi.todayCount).toHaveBeenCalledTimes(1);
    expect(store.getState().todayPicksCount).toBe(20);
  });
  it('精选页已上报计数时保留该值，避免重复获取', async () => {
    const { store } = fixture();
    store.getState()._setPathname('/today-picks');
    store.getState().reportTodayPicksTotal(37);
    vi.mocked(favoritesApi.index).mockResolvedValueOnce(index());
    await store.getState().refreshCounts();
    expect(contentsApi.todayCount).not.toHaveBeenCalled();
    expect(store.getState().todayPicksCount).toBe(37);
  });
  it('旧账号索引晚到，不写进新账号状态', async () => {
    const { auth, store } = fixture();
    const pending = deferred<ReturnType<typeof index>>();
    vi.mocked(favoritesApi.index).mockReturnValueOnce(pending.promise);
    const loading = store.getState()._loadFromIndex();
    auth.setState({ currentUser: user(2) });
    store.getState()._loadFromStorage(2);
    pending.resolve(index());
    await loading;
    expect([...store.getState().favorites]).toEqual([]);
    expect(store.getState().favoriteTotal).toBe(0);
  });
  it('退出后旧计数请求不能恢复私人计数与收藏', async () => {
    const { auth, store } = fixture();
    const pending = deferred<ReturnType<typeof index>>();
    vi.mocked(favoritesApi.index).mockReturnValueOnce(pending.promise);
    const loading = store.getState().refreshCounts();
    auth.setState({ currentUser: null });
    store.getState()._clear();
    pending.resolve(index());
    await loading;
    expect(store.getState().favoriteTotal).toBe(0);
    expect(store.getState().sourceCount).toBe(0);
    expect(store.getState().todayPicksCount).toBe(0);
    expect([...store.getState().favorites]).toEqual([]);
  });
  it('旧收藏写响应不改变新账号，finally不清除新账号同一按钮的pending', async () => {
    const { auth, store } = fixture();
    const old = deferred<{ is_favorited: boolean; favorite_id: number }>();
    const fresh = deferred<{ is_favorited: boolean; favorite_id: number }>();
    vi.mocked(contentsApi.toggleFavorite).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const first = store.getState().toggleFavorite(41);
    auth.setState({ currentUser: user(2) });
    store.getState()._loadFromStorage(2);
    const second = store.getState().toggleFavorite(41);
    expect(contentsApi.toggleFavorite).toHaveBeenCalledTimes(2);
    old.resolve({ is_favorited: true, favorite_id: 101 });
    await first;
    expect(store.getState().favorites.has(41)).toBe(false);
    expect(store.getState().favoritePendingIds.has(41)).toBe(true);
    fresh.resolve({ is_favorited: true, favorite_id: 202 });
    await second;
    expect(store.getState().favorites.has(41)).toBe(true);
    expect(store.getState().favoritePendingIds.size).toBe(0);
  });
  it('查询收藏ID期间换号，停止后续删除请求', async () => {
    const { auth, store } = fixture();
    store.setState({ favoriteTargets: new Set(['content:41']) });
    const pending = deferred<{ items: Array<{ target_key: string; is_favorited: boolean; favorite_id: number }> }>();
    vi.mocked(favoritesApi.state).mockReturnValueOnce(pending.promise);
    const action = store.getState().toggleFavoriteTarget({ target_type: 'content', target_id: 41 });
    auth.setState({ currentUser: user(2) });
    store.getState()._loadFromStorage(2);
    pending.resolve({ items: [{ target_key: '41', is_favorited: true, favorite_id: 101 }] });
    await action;
    expect(favoritesApi.delete).not.toHaveBeenCalled();
    expect(store.getState().favoriteTotal).toBe(0);
  });
  it('相同账号的较早索引不能覆盖较新的索引', async () => {
    const { store } = fixture();
    const old = deferred<ReturnType<typeof index>>();
    vi.mocked(favoritesApi.index).mockReturnValueOnce(old.promise).mockResolvedValueOnce(index(42));
    const first = store.getState()._loadFromIndex();
    await store.getState()._loadFromIndex();
    old.resolve(index(41));
    await first;
    expect([...store.getState().favorites]).toEqual([42]);
  });
  it('新收藏成功后，之前读取的旧索引不能把它抹掉', async () => {
    const { store } = fixture();
    const pending = deferred<ReturnType<typeof index>>();
    vi.mocked(favoritesApi.index).mockReturnValueOnce(pending.promise);
    const read = store.getState()._loadFromIndex();
    vi.mocked(contentsApi.toggleFavorite).mockResolvedValueOnce({ is_favorited: true, favorite_id: 202 });
    await store.getState().toggleFavorite(42);
    pending.resolve(index(41));
    await read;
    expect([...store.getState().favorites]).toEqual([42]);
  });
  it('收藏修改使旧索引失效时，仍接收同一账号独立的信源和精选计数', async () => {
    const { store } = fixture();
    const pending = deferred<ReturnType<typeof index>>();
    vi.mocked(favoritesApi.index).mockReturnValueOnce(pending.promise);
    const read = store.getState().refreshCounts();
    vi.mocked(contentsApi.toggleFavorite).mockResolvedValueOnce({ is_favorited: true, favorite_id: 202 });
    await store.getState().toggleFavorite(42);
    pending.resolve(index(41));
    await read;
    expect([...store.getState().favorites]).toEqual([42]);
    expect(store.getState().sourceCount).toBe(4);
    expect(store.getState().todayPicksCount).toBe(20);
  });
});
