import { beforeEach, describe, expect, it, vi } from 'vitest';
const runtime = vi.hoisted(() => ({ effects: [] as Array<() => void | (() => void)>, setters: [] as Array<ReturnType<typeof vi.fn>> }));
vi.mock('react', () => ({
  useCallback: (callback: unknown) => callback,
  useRef: (value: unknown) => ({ current: value }),
  useState: (initial: unknown) => { const set = vi.fn(); runtime.setters.push(set); return [initial, set]; },
  useEffect: (effect: () => void | (() => void)) => { runtime.effects.push(effect); },
  useLayoutEffect: (effect: () => void) => { effect(); },
}));
import { useFetch } from './useFetch';
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => { runtime.effects = []; runtime.setters = []; });

describe('useFetch effect lifecycle', () => {
  it('依赖或enabled变化清理旧effect后，迟到成功不能写回', async () => {
    const pending = deferred<string>();
    useFetch(() => pending.promise, ['old']);
    const cleanup = runtime.effects[0]();
    expect(typeof cleanup).toBe('function');
    cleanup!();
    pending.resolve('old private result');
    await pending.promise;
    await Promise.resolve();
    expect(runtime.setters[0]).not.toHaveBeenCalled();
    expect(runtime.setters[1]).not.toHaveBeenCalledWith(false);
  });
  it('旧effect清理后的失败与finally不能覆盖新状态', async () => {
    const pending = deferred<string>();
    useFetch(() => pending.promise, ['old']);
    const cleanup = runtime.effects[0]();
    expect(typeof cleanup).toBe('function');
    cleanup!();
    pending.reject(new Error('stale failure'));
    await pending.promise.catch(() => {});
    await Promise.resolve();
    expect(runtime.setters[2]).not.toHaveBeenCalledWith('stale failure');
    expect(runtime.setters[1]).not.toHaveBeenCalledWith(false);
  });
  it('禁用状态下手动重试也不会触发无权限或无对象请求', async () => {
    const fetcher = vi.fn().mockResolvedValue('private result');
    const query = useFetch(fetcher, [], { enabled: false, initialLoading: false });
    runtime.effects[0]();
    expect(await query.refetch()).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
