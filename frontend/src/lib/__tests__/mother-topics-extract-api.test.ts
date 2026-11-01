import { afterEach, describe, expect, it, vi } from 'vitest';
import { motherTopicsApi } from '@/lib/api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('motherTopicsApi.extractKeywords', () => {
  it('POSTs the description to the extract endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ keywords: ['AI工具', '新能源车', '充电桩'] }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await motherTopicsApi.extractKeywords('我想看 AI 工具和新能源车相关的内容');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/mother-topics/extract-keywords');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
    expect(JSON.parse(init.body as string)).toEqual({ description: '我想看 AI 工具和新能源车相关的内容' });
    expect(result.keywords).toEqual(['AI工具', '新能源车', '充电桩']);
  });

  it('preserves the explicit 502 detail instead of faking success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: '关键词提取失败：模型链路熔断中，可直接手动填写关键词' }, 502),
      ),
    );

    await expect(motherTopicsApi.extractKeywords('描述')).rejects.toMatchObject({
      status: 502,
      message: '关键词提取失败：模型链路熔断中，可直接手动填写关键词',
    });
  });
});
