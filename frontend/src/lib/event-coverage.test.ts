import { describe, expect, it, vi } from 'vitest';
import { createEventCoverageLoader } from './event-coverage';
import type { CoverageState } from './event-coverage';
import type { ContentEventCoverage, ContentNormalizationSummary } from '@/types';

const member = (id: number) => ({ id, title: `report-${id}`, url: `https://example.com/${id}`, source_name: 'Publisher', source_type: 'RSS', relation_type: 'duplicate' as const });
const seed: ContentEventCoverage = {
  event_id: 10, version: 2, canonical_id: 1, representative_id: 2,
  member_count: 7, source_count: 3, members: [member(1), member(3), member(4), member(5), member(6)],
  member_offset: 0, next_offset: 5, has_more: true,
};
const response = (event: ContentEventCoverage | null) => ({ content_id: 2, event });
const remaining = { ...seed, members: [member(7), member(8)], member_offset: 5, next_offset: 7, has_more: false };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe('event coverage request ownership', () => {
  it('loads the remaining reports using the same event/version and excludes the displayed report', async () => {
    const fetchPage = vi.fn().mockResolvedValue(response(remaining));
    const publish = vi.fn();
    await createEventCoverageLoader(2, seed, fetchPage, publish).loadMore();
    expect(fetchPage).toHaveBeenCalledWith(2, { member_offset: 5, member_limit: 20, expected_event_id: 10, expected_version: 2 });
    const final = publish.mock.lastCall![0] as CoverageState;
    expect(final.coverage!.members.map(item => item.id)).toEqual([1, 3, 4, 5, 6, 7, 8]);
    expect(final.loading).toBe(false);
    expect(final.coverage!.has_more).toBe(false);
  });

  it('preserves loaded reports and retries the same offset after a failed request', async () => {
    const fetchPage = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(response(remaining));
    const publish = vi.fn();
    const loader = createEventCoverageLoader(2, seed, fetchPage, publish);
    await loader.loadMore();
    expect(publish.mock.lastCall![0]).toMatchObject({ loading: false, error: '其它报道加载失败，请重试', coverage: seed });
    await loader.loadMore();
    expect(fetchPage.mock.calls[1][1].member_offset).toBe(5);
    expect(publish.mock.lastCall![0].coverage.members).toHaveLength(7);
  });

  it('reloads from zero on version conflict instead of mixing event versions', async () => {
    const fresh = { ...seed, version: 3, members: [member(9)], member_count: 1, next_offset: 1, has_more: false };
    const fetchPage = vi.fn().mockRejectedValueOnce({ status: 409 }).mockResolvedValueOnce(response(fresh));
    const publish = vi.fn();
    await createEventCoverageLoader(2, seed, fetchPage, publish).loadMore();
    expect(fetchPage.mock.calls[1][1]).toEqual({ member_offset: 0, member_limit: 20 });
    expect(publish.mock.lastCall![0]).toMatchObject({ changed: true, coverage: fresh });
    expect(publish.mock.calls.some(([state]) => state.changed && state.loading && state.coverage === null)).toBe(true);
  });

  it('does not resurrect stale reports when reload fails after a version conflict', async () => {
    const fetchPage = vi.fn().mockRejectedValueOnce({ status: 409 }).mockRejectedValueOnce(new Error('offline'));
    const publish = vi.fn();
    const loader = createEventCoverageLoader(2, seed, fetchPage, publish);
    await loader.loadMore();
    expect(publish.mock.lastCall![0]).toMatchObject({ coverage: null, changed: true, loading: false });
    fetchPage.mockResolvedValueOnce(response({ ...seed, members: [member(9)], member_count: 1, next_offset: 1, has_more: false }));
    await loader.loadMore();
    expect(fetchPage.mock.lastCall![1].member_offset).toBe(0);
  });

  it.each(['resolve', 'reject'] as const)('ignores late %s and finally after a report is unmounted', async (outcome) => {
    const pending = deferred<ReturnType<typeof response>>();
    const publish = vi.fn();
    const loader = createEventCoverageLoader(2, seed, () => pending.promise, publish);
    const loading = loader.loadMore();
    loader.cancel();
    const callsBefore = publish.mock.calls.length;
    if (outcome === 'resolve') pending.resolve(response(remaining));
    else pending.reject(new Error('late error'));
    await loading;
    expect(publish).toHaveBeenCalledTimes(callsBefore);
  });

  it('does not send a second request for a rapid double click', async () => {
    const pending = deferred<ReturnType<typeof response>>();
    const fetchPage = vi.fn(() => pending.promise);
    const loader = createEventCoverageLoader(2, seed, fetchPage, vi.fn());
    const first = loader.loadMore();
    await loader.loadMore();
    expect(fetchPage).toHaveBeenCalledTimes(1);
    pending.resolve(response(remaining));
    await first;
  });

  it.each([
    { ...remaining, event_id: 999 },
    { ...remaining, version: 999 },
    { ...remaining, representative_id: 999 },
    { ...remaining, member_offset: 0 },
    { ...remaining, members: [member(2), member(8)] },
    { ...remaining, members: [member(6), member(8)] },
  ])('rejects a response from a different scope or with duplicate reports', async (page) => {
    const publish = vi.fn();
    await createEventCoverageLoader(2, seed, vi.fn().mockResolvedValue(response(page)), publish).loadMore();
    expect(publish.mock.lastCall![0]).toMatchObject({ coverage: seed, error: '其它报道加载失败，请重试', loading: false });
  });

  it('refreshes legacy summaries without appending from an unknown version', async () => {
    const legacy: ContentNormalizationSummary = { canonical_id: 1, members: seed.members, member_count: 7, source_count: 3, has_more: true };
    const fetchPage = vi.fn().mockResolvedValue(response({ ...seed, members: [member(9)], member_count: 1, next_offset: 1, has_more: false }));
    const publish = vi.fn();
    await createEventCoverageLoader(2, legacy, fetchPage, publish).loadMore();
    expect(fetchPage.mock.calls[0][1]).toEqual({ member_offset: 0, member_limit: 20 });
    expect(publish.mock.lastCall![0].coverage.members.map((item: { id: number }) => item.id)).toEqual([9]);
  });
});
