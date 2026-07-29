import { afterEach, describe, expect, it, vi } from 'vitest';
import { contentEventsAdminApi } from '@/lib/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('contentEventsAdminApi', () => {
  it('sends review filters as server-side pagination parameters', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [],
        total: 0,
        page: 2,
        page_size: 20,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await contentEventsAdminApi.listReviews({
      page: 2,
      page_size: 20,
      review_status: 'pending',
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/admin/content-events/reviews?page=2&page_size=20&review_status=pending',
      expect.objectContaining({
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      }),
    );
  });

  it('forwards a fresh idempotency key on normalization requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        accepted: true,
        idempotency_key: 'run-123',
        mode: 'shadow',
        scope: 'public',
        owner_user_id: null,
        result: {},
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await contentEventsAdminApi.normalize(
      {
        hours: 24,
        mode: 'shadow',
        scope: 'public',
      },
      'run-123',
    );

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/admin/content-events/normalize',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Idempotency-Key': 'run-123',
        }),
      }),
    );
  });

  it('preserves HTTP 409 for optimistic-concurrency messaging', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: 'event version conflict' }, 409),
      ),
    );

    await expect(
      contentEventsAdminApi.reviewMember(9, {
        decision: 'accept',
        relation_type: 'duplicate',
        reason: '同一事件',
        expected_version: 3,
      }),
    ).rejects.toMatchObject({
      status: 409,
      message: 'event version conflict',
    });
  });
});
