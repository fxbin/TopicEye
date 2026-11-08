import { describe, expect, it, vi, beforeEach } from 'vitest';
import { favoritesApi } from '@/lib/api';
import { startContentWorkflow } from './workflow';

vi.mock('@/lib/api', () => ({ favoritesApi: { state: vi.fn(), update: vi.fn() } }));
beforeEach(() => { vi.resetAllMocks(); });
function deferred<T>() {
  let resolve!: (result: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('推进选题的账号边界', () => {
  it('收藏请求期间换号，不继续查新账号收藏或导航', async () => {
    let active = true;
    const pending = deferred<boolean>();
    const push = vi.fn();
    const work = startContentWorkflow({ contentId: 1, title: '私人素材', isFavorited: false, toggleFavorite: () => pending.promise, router: { push }, isActive: () => active });
    active = false;
    pending.resolve(true);
    await work;
    expect(favoritesApi.state).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });
  it('收藏索引期间换号，不更新新账号收藏或导航', async () => {
    let active = true;
    const pending = deferred<Awaited<ReturnType<typeof favoritesApi.state>>>();
    vi.mocked(favoritesApi.state).mockReturnValueOnce(pending.promise);
    const push = vi.fn();
    const work = startContentWorkflow({ contentId: 1, title: '私人素材', isFavorited: true, toggleFavorite: vi.fn(), router: { push }, isActive: () => active });
    active = false;
    pending.resolve({ items: [{ target_key: 'content:1', is_favorited: true, favorite_id: 11 }] });
    await work;
    expect(favoritesApi.update).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });
  it('收藏更新期间换号，旧操作完成后不触发导航', async () => {
    let active = true;
    const pending = deferred<Awaited<ReturnType<typeof favoritesApi.update>>>();
    vi.mocked(favoritesApi.state).mockResolvedValueOnce({ items: [{ target_key: 'content:1', is_favorited: true, favorite_id: 11 }] });
    vi.mocked(favoritesApi.update).mockReturnValueOnce(pending.promise);
    const push = vi.fn();
    const work = startContentWorkflow({ contentId: 1, title: '私人素材', isFavorited: true, toggleFavorite: vi.fn(), router: { push }, isActive: () => active });
    await Promise.resolve();
    expect(favoritesApi.update).toHaveBeenCalledWith(11, { status: 'researching' });
    active = false;
    pending.resolve({} as Awaited<ReturnType<typeof favoritesApi.update>>);
    await work;
    expect(push).not.toHaveBeenCalled();
  });
  it('账号保持有效时完成收藏更新并打开对应筛选', async () => {
    vi.mocked(favoritesApi.state).mockResolvedValueOnce({ items: [{ target_key: 'content:1', is_favorited: true, favorite_id: 11 }] });
    const push = vi.fn();
    await startContentWorkflow({ contentId: 1, title: '素材', isFavorited: false, toggleFavorite: vi.fn().mockResolvedValue(true), router: { push } });
    expect(favoritesApi.update).toHaveBeenCalledWith(11, { status: 'researching' });
    expect(push).toHaveBeenCalledWith('/favorites?target_type=content&status=researching&keyword=%E7%B4%A0%E6%9D%90');
  });
});
