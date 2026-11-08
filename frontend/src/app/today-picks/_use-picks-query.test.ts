import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DependencyList } from 'react';

const query = vi.hoisted(() => ({ data: null as unknown, deps: [] as DependencyList, fetch: null as null | (() => Promise<unknown>) }));
vi.mock('react', () => ({ useCallback: (callback: unknown) => callback }));
vi.mock('@/hooks/useFetch', () => ({ useFetch: (fetcher: () => Promise<unknown>, deps: DependencyList) => {
  query.fetch = fetcher;
  query.deps = deps;
  return { data: query.data, loading: false, error: null, refetch: fetcher };
} }));
vi.mock('@/lib/api', () => ({ contentsApi: { todayPicks: vi.fn() } }));
import { contentsApi } from '@/lib/api';
import { usePicksQuery } from './_use-picks-query';

beforeEach(() => {
  vi.resetAllMocks();
  query.data = null;
  query.fetch = null;
  vi.mocked(contentsApi.todayPicks).mockResolvedValue({ items: [], total: 0, topics: [], event_members_hidden: 0 });
});

describe('精选查询账号归属', () => {
  it.each([2, null])('切换为%s后立即隐藏旧账号已完成的结果，并要求新请求', async (nextOwner) => {
    usePicksQuery(1, '', '', 'today');
    const oldDeps = query.deps;
    const oldResponse = await query.fetch!();
    query.data = oldResponse;
    expect(usePicksQuery(1, '', '', 'today').data).toBe(oldResponse);
    expect(usePicksQuery(nextOwner, '', '', 'today').data).toBeNull();
    expect(query.deps).not.toEqual(oldDeps);
    const freshResponse = await query.fetch!();
    query.data = freshResponse;
    expect(usePicksQuery(nextOwner, '', '', 'today').data).toBe(freshResponse);
  });

  it('旧账号首屏迟到时仍携带发起身份，不能被标成新账号结果', async () => {
    let finish!: (result: Awaited<ReturnType<typeof contentsApi.todayPicks>>) => void;
    vi.mocked(contentsApi.todayPicks).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    usePicksQuery(1, 'AI', '', 'today');
    const pending = query.fetch!();
    usePicksQuery(2, 'AI', '', 'today');
    finish({ items: [], total: 1, topics: [], event_members_hidden: 0 });
    query.data = await pending;
    expect(usePicksQuery(2, 'AI', '', 'today').data).toBeNull();
  });

  it('换筛选后隐藏旧结果，首屏与追加页保持同一参数口径', async () => {
    usePicksQuery(1, 'AI', 'article', 'week');
    query.data = await query.fetch!();
    const next = usePicksQuery(1, '职场', 'article', 'week');
    expect(next.data).toBeNull();
    expect(next.buildParams(40)).toEqual({ category: '职场', content_type: 'article', time_range: 'week', limit: 40, offset: 40 });
    await query.fetch!();
    expect(contentsApi.todayPicks).toHaveBeenLastCalledWith({ ...next.buildParams(40), offset: 0 });
  });
});
