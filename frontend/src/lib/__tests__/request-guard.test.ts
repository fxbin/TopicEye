import { describe, expect, it, vi } from 'vitest';
import { createRequestGuard } from '../request-guard';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe('query response ownership', () => {
  it('lets a mutation observe its query without replacing an active load', () => {
    const guard = createRequestGuard();
    const load = guard.begin();
    const mutation = guard.capture();
    expect(load()).toBe(true);
    expect(mutation()).toBe(true);
    guard.begin();
    expect(load()).toBe(false);
    expect(mutation()).toBe(false);
  });
  it('keeps the latest article/query when an older response finishes last', async () => {
    const guard = createRequestGuard();
    const publish = vi.fn();
    const first = deferred<string>();
    const activeA = guard.begin();
    const pendingA = first.promise.then((value) => { if (activeA()) publish(value); });
    const activeB = guard.begin();
    if (activeB()) publish('article B');
    first.resolve('article A');
    await pendingA;
    expect(publish.mock.calls).toEqual([['article B']]);
  });

  it('ignores stale failures and finally handlers while the new query is pending', async () => {
    const guard = createRequestGuard();
    const error = vi.fn();
    const settled = vi.fn();
    const old = deferred<string>();
    const activeOld = guard.begin();
    const pending = old.promise.catch((reason) => { if (activeOld()) error(reason); })
      .finally(() => { if (activeOld()) settled(); });
    guard.begin();
    old.reject(new Error('old query failed'));
    await pending;
    expect(error).not.toHaveBeenCalled();
    expect(settled).not.toHaveBeenCalled();
  });

  it('invalidates translation/load responses on close, unmount, or empty search', () => {
    const guard = createRequestGuard();
    const active = guard.begin();
    guard.invalidate();
    expect(active()).toBe(false);
    expect(guard.begin()()).toBe(true);
  });

  it('does not revive an old request when returning from A to B to A', () => {
    const guard = createRequestGuard();
    const firstA = guard.begin();
    const b = guard.begin();
    const secondA = guard.begin();
    expect(firstA()).toBe(false);
    expect(b()).toBe(false);
    expect(secondA()).toBe(true);
  });
});
