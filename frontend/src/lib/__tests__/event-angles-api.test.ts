import { afterEach, describe, expect, it, vi } from 'vitest';
import { contentsApi } from '@/lib/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('contentsApi.analyzeEventAngles', () => {
  it('POSTs the content id without local caching side effects', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      status: 'ok',
      event_id: 11,
      version: 3,
      truncated: false,
      analyzed_count: 3,
      covered_angles: ['官方通报口径'],
      scarce_angles: [{ angle: '成本视角', reason: 'r', refs: [{ content_id: 8, title: '成员八' }] }],
      audience_questions: ['会持续多久？'],
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await contentsApi.analyzeEventAngles(8);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/contents/8/event/angles',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    );
    expect(result.status).toBe('ok');
    expect(result.scarce_angles[0].refs[0]).toMatchObject({ content_id: 8, title: '成员八' });
  });

  it('parses the explicit no_event contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'no_event' })));
    const result = await contentsApi.analyzeEventAngles(9);
    expect(result).toEqual({ status: 'no_event' });
  });

  it('preserves the explicit 502 detail instead of faking success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: '事件角度分析失败：模型链路熔断中，请稍后重试' }, 502)));
    await expect(contentsApi.analyzeEventAngles(8)).rejects.toMatchObject({
      status: 502,
      message: '事件角度分析失败：模型链路熔断中，请稍后重试',
    });
  });

  it('surfaces 404 for missing or invisible content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Content not found' }, 404)));
    await expect(contentsApi.analyzeEventAngles(404)).rejects.toMatchObject({ status: 404 });
  });
});
