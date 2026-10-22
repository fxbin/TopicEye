import { describe, expect, it } from 'vitest';
import { userStatusAction } from './_user-actions';

describe('user access action contract', () => {
  it('warns about login loss only when disabling an active user', () => {
    expect(userStatusAction(true)).toEqual({ next: false, verb: '封禁', warning: '该用户将立即无法登录。' });
  });
  it('reenables a banned user without claiming they will lose access', () => {
    expect(userStatusAction(false)).toEqual({ next: true, verb: '解封', warning: '' });
  });
});
