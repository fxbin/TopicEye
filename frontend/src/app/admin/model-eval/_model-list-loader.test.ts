import { describe, expect, it, vi } from 'vitest';
import type { LlmModelItem } from '@/types/models';
import { createModelListLoader } from './_model-list-loader';

function deferred() {
  let resolve!: (result: { models: LlmModelItem[] }) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<{ models: LlmModelItem[] }>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function setup() {
  const first = deferred();
  const second = deferred();
  const onData = vi.fn();
  const onError = vi.fn();
  const onSettled = vi.fn();
  const loader = createModelListLoader({
    fetch: vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise),
    onData, onError, onSettled,
  });
  return { first, second, onData, onError, onSettled, loader };
}

const models = (aEnabled: boolean, bEnabled: boolean) => [
  { id: 1, enabled: aEnabled }, { id: 2, enabled: bEnabled },
] as LlmModelItem[];

describe('model list refresh response ownership', () => {
  it('keeps both models disabled when the older mutation read finishes last', async () => {
    const { loader, first, second, onData, onSettled } = setup();
    const afterA = loader.refresh();
    const afterB = loader.refresh();
    second.resolve({ models: models(false, false) });
    await afterB;
    first.resolve({ models: models(false, true) });
    await afterA;
    expect(onData.mock.calls).toEqual([[models(false, false)]]);
    expect(onSettled).toHaveBeenCalledTimes(1);
  });

  it.each([false, true])('ignores an older failure when the latest read has settled: %s', async (latestSettled) => {
    const { loader, first, second, onError, onSettled } = setup();
    const oldRead = loader.refresh();
    const currentRead = loader.refresh();
    if (latestSettled) {
      second.resolve({ models: models(false, false) });
      await currentRead;
    }
    first.reject(new Error('obsolete failure'));
    await expect(oldRead).resolves.toBeUndefined();
    expect(onError.mock.calls).toEqual([[null], [null]]);
    expect(onSettled).toHaveBeenCalledTimes(latestSettled ? 1 : 0);
    if (!latestSettled) {
      second.resolve({ models: models(false, false) });
      await currentRead;
    }
  });

  it('keeps mutation awaits pending until the read settles and propagates the current failure', async () => {
    const { loader, first, onError, onSettled } = setup();
    const finished = vi.fn();
    const read = loader.refresh();
    const outcome = read.then(finished, finished);
    await Promise.resolve();
    expect(finished).not.toHaveBeenCalled();
    const error = new Error('current refresh failed');
    first.reject(error);
    await expect(read).rejects.toBe(error);
    await outcome;
    expect(onError.mock.calls).toEqual([[null], ['current refresh failed']]);
    expect(onSettled).toHaveBeenCalledTimes(1);
  });

  it('invalidates data, errors and cleanup when leaving the page', async () => {
    const { loader, first, onData, onError, onSettled } = setup();
    const read = loader.refresh();
    loader.invalidate();
    first.reject(new Error('finished after unmount'));
    await read;
    expect(onData).not.toHaveBeenCalled();
    expect(onError.mock.calls).toEqual([[null]]);
    expect(onSettled).not.toHaveBeenCalled();
  });
});
