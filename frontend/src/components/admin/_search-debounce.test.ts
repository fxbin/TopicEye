import { afterEach, describe, expect, it, vi } from 'vitest';
import { createDebouncedSearch } from './_search-debounce';

afterEach(() => vi.useRealTimers());
describe('admin search drafts', () => {
  it('does not restore a queued search after clear-all resets the filters', () => {
    vi.useFakeTimers();
    const commit = vi.fn();
    const search = createDebouncedSearch(commit, 300);
    search.schedule('new draft');
    vi.advanceTimersByTime(200);
    search.cancel();
    vi.advanceTimersByTime(300);
    expect(commit).not.toHaveBeenCalled();
    search.schedule('after reset');
    vi.advanceTimersByTime(300);
    expect(commit).toHaveBeenCalledExactlyOnceWith('after reset');
  });
  it('commits only the last draft in a typing burst', () => {
    vi.useFakeTimers();
    const commit = vi.fn();
    const search = createDebouncedSearch(commit, 300);
    search.schedule('A'); vi.advanceTimersByTime(100);
    search.schedule('AB'); vi.advanceTimersByTime(100);
    search.schedule('ABC'); vi.advanceTimersByTime(300);
    expect(commit).toHaveBeenCalledExactlyOnceWith('ABC');
  });
});
