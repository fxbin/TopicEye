import { afterEach, describe, expect, it, vi } from 'vitest';
import { trendsApi } from '@/lib/api';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('trendsApi evidence requests', () => {
  it('requests one frozen topic snapshot with server-side paging and filters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal('fetch', fetchMock);

    await trendsApi.topicEvidence(42, '2026-08-05', {
      filter: 'evidenced',
      page: 2,
      page_size: 10,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/trends/topics/42/evidence?date=2026-08-05&filter=evidenced&page=2&page_size=10',
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    );
  });

  it('URL-encodes the keyword evidence scope', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal('fetch', fetchMock);

    await trendsApi.keywordEvidence('AI writing', { days: 14, filter: 'selected' });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/trends/keywords/evidence?keyword=AI+writing&days=14&filter=selected&page=1&page_size=20',
      expect.any(Object),
    );
  });
});
