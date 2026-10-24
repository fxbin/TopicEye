import { describe, expect, it, vi } from 'vitest';
import { runTopicMutation } from './_mutation';

describe('mother topic form submission', () => {
  it('preserves the draft and re-enables save after a rejected mutation', async () => {
    let draft = '我的母题';
    const pending = vi.fn();
    const error = vi.fn();
    const success = vi.fn(() => { draft = ''; });
    expect(await runTopicMutation(async () => { throw new Error('network unavailable'); }, { pending, error, success })).toBe(false);
    expect(draft).toBe('我的母题');
    expect(success).not.toHaveBeenCalled();
    expect(pending.mock.calls).toEqual([[true], [false]]);
    expect(error.mock.calls).toEqual([[null], ['network unavailable']]);
  });

  it('clears the previous error and resets once on successful retry', async () => {
    const state = { pending: vi.fn(), error: vi.fn(), success: vi.fn() };
    await runTopicMutation(async () => { throw new Error('failed'); }, state);
    expect(await runTopicMutation(async () => {}, state)).toBe(true);
    expect(state.success).toHaveBeenCalledOnce();
    expect(state.error.mock.calls).toEqual([[null], ['failed'], [null]]);
    expect(state.pending.mock.calls).toEqual([[true], [false], [true], [false]]);
  });
});
