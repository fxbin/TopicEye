import { afterEach, describe, expect, it, vi } from 'vitest';
import { mcpOAuthApi } from '@/lib/api';
import { sanitizeReturnTo } from '@/lib/navigation';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('mcpOAuthApi consent endpoints', () => {
  it('fetches authorize-info with the request id encoded', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ request_id: 'r1', client_name: 'Claude', client_uri: null, scopes: [], redirect_host: '127.0.0.1' }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const info = await mcpOAuthApi.authorizeInfo('r 1/2');
    expect(info.client_name).toBe('Claude');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/mcp-oauth/authorize-info?request_id=r%201%2F2',
      expect.any(Object),
    );
  });

  it('posts approve/deny decisions as JSON bodies', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ redirect_to: 'http://127.0.0.1:1/cb?code=x' })),
    );
    vi.stubGlobal('fetch', fetchMock);

    await mcpOAuthApi.approve('req-1');
    await mcpOAuthApi.deny('req-1');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/mcp-oauth/approve',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ request_id: 'req-1' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/mcp-oauth/deny',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});

describe('sanitizeReturnTo', () => {
  it('keeps in-site paths with query strings', () => {
    expect(sanitizeReturnTo('/mcp/authorize?request_id=abc')).toBe('/mcp/authorize?request_id=abc');
    expect(sanitizeReturnTo('/profile')).toBe('/profile');
  });

  it('rejects open-redirect shapes and falls back to home', () => {
    expect(sanitizeReturnTo('//evil.com')).toBe('/');
    expect(sanitizeReturnTo('https://evil.com')).toBe('/');
    expect(sanitizeReturnTo('/\\evil.com')).toBe('/');
    expect(sanitizeReturnTo('javascript:alert(1)')).toBe('/');
    expect(sanitizeReturnTo(null)).toBe('/');
    expect(sanitizeReturnTo('')).toBe('/');
  });
});
