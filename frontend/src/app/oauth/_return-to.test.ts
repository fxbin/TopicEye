import { describe, expect, it } from 'vitest';
import { consumeOauthReturnTo, rememberOauthReturnTo } from './_return-to';

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  };
}

describe('OAuth login return path', () => {
  it('returns to the full MCP consent query exactly once', () => {
    const store = storage();
    rememberOauthReturnTo(store, '/mcp/authorize?request_id=abc%2B123');
    expect(consumeOauthReturnTo(store)).toBe('/mcp/authorize?request_id=abc%2B123');
    expect(consumeOauthReturnTo(store)).toBe('/');
  });

  it.each(['https://evil.example', '//evil.example', 'javascript:alert(1)'])('rejects unsafe return path %s', (path) => {
    const store = storage();
    rememberOauthReturnTo(store, path);
    expect(consumeOauthReturnTo(store)).toBe('/');
  });

  it('overwrites a previous login destination on a fresh OAuth attempt', () => {
    const store = storage();
    rememberOauthReturnTo(store, '/mcp/authorize?request_id=old');
    rememberOauthReturnTo(store, '/');
    expect(consumeOauthReturnTo(store)).toBe('/');
  });
});
