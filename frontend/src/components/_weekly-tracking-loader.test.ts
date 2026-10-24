import { describe, expect, it, vi } from 'vitest';
import { createWeeklyTrackingLoader, type WeeklyTrackingData } from './_weekly-tracking-loader';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const tracking = (week_key: string): WeeklyTrackingData => ({ week_key, week_range: week_key, marks: [], total: 0 });
function setup(fetch = vi.fn(async (key: string) => tracking(key))) {
  const state = { data: vi.fn(), pending: vi.fn(), error: vi.fn() };
  return { fetch, state, loader: createWeeklyTrackingLoader(fetch, state) };
}

describe('weekly pick tracking navigation', () => {
  it('clears the old week immediately and ignores its late response', async () => {
    const { fetch, loader, state } = setup();
    const old = deferred<WeeklyTrackingData>();
    fetch.mockImplementationOnce(() => old.promise);
    const first = loader.load('2026-W41');
    await loader.load('2026-W42');
    old.resolve(tracking('2026-W41'));
    await first;
    expect(state.data.mock.calls.map(([value]) => value?.week_key ?? null)).toEqual([null, null, '2026-W42']);
  });

  it('settles missing keys without requesting or leaving a spinner', async () => {
    const { fetch, loader, state } = setup();
    await loader.load();
    expect(fetch).not.toHaveBeenCalled();
    expect(state.pending.mock.calls).toEqual([[false]]);
    expect(state.data).toHaveBeenCalledWith(null);
  });

  it('shows failures and permits a successful retry', async () => {
    const { fetch, loader, state } = setup();
    fetch.mockRejectedValueOnce(new Error('offline'));
    await loader.load('2026-W42');
    expect(state.error).toHaveBeenLastCalledWith('offline');
    expect(state.pending).toHaveBeenLastCalledWith(false);
    await loader.load('2026-W42');
    expect(state.error).toHaveBeenLastCalledWith(null);
    expect(state.data).toHaveBeenLastCalledWith(tracking('2026-W42'));
  });

  it('ignores errors and cleanup from an unmounted week', async () => {
    const { fetch, loader, state } = setup();
    const old = deferred<WeeklyTrackingData>();
    fetch.mockImplementationOnce(() => old.promise);
    const first = loader.load('2026-W41');
    loader.cancel();
    old.reject(new Error('late failure'));
    await first;
    expect(state.error.mock.calls).toEqual([[null]]);
    expect(state.pending.mock.calls).toEqual([[true]]);
  });
});
