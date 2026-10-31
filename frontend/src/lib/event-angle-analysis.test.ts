import { describe, expect, it, vi } from 'vitest';
import { angleRefHref, createEventAngleAnalysisController } from './event-angle-analysis';
import type { AngleAnalysisState } from './event-angle-analysis';
import type { EventAngleAnalysis } from '@/types';

const analysis: EventAngleAnalysis = {
  status: 'ok',
  event_id: 11,
  version: 3,
  truncated: false,
  analyzed_count: 3,
  covered_angles: ['官方通报口径', '发布会时间线'],
  scarce_angles: [
    { angle: '受影响用户成本视角', reason: '列表只覆盖官方口径', refs: [{ content_id: 7, title: '主报道' }, { content_id: 8, title: '成员八' }] },
  ],
  audience_questions: ['涨价会持续多久？'],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe('event angle analysis controller', () => {
  it('publishes loading then the analysis result', async () => {
    const publish = vi.fn();
    await createEventAngleAnalysisController(8, vi.fn().mockResolvedValue(analysis), publish).run();

    const states = publish.mock.calls.map(([state]) => state as AngleAnalysisState);
    expect(states[0]).toMatchObject({ loading: true, error: null, analysis: null });
    expect(states.at(-1)).toMatchObject({ loading: false, error: null, analysis });
    expect(states.at(-1)!.analysis!.scarce_angles[0].refs).toEqual([
      { content_id: 7, title: '主报道' },
      { content_id: 8, title: '成员八' },
    ]);
  });

  it('surfaces failures explicitly and retries with a fresh request', async () => {
    const failure = Object.assign(new Error('事件角度分析失败：模型链路熔断中，请稍后重试'), { status: 502 });
    const fetchAnalysis = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce(analysis);
    const publish = vi.fn();
    const controller = createEventAngleAnalysisController(8, fetchAnalysis, publish);

    await controller.run();
    expect(publish.mock.lastCall![0]).toMatchObject({ loading: false, error: '事件角度分析失败：模型链路熔断中，请稍后重试' });
    expect(fetchAnalysis).toHaveBeenCalledTimes(1);

    // 重试 = 再点一次按钮，重新请求而不是回放缓存结果
    await controller.run();
    expect(fetchAnalysis).toHaveBeenCalledTimes(2);
    expect(publish.mock.lastCall![0]).toMatchObject({ loading: false, error: null, analysis });
  });

  it('falls back to a generic message when the error carries none', async () => {
    const publish = vi.fn();
    await createEventAngleAnalysisController(8, vi.fn().mockRejectedValue({ status: 502 }), publish).run();
    expect(publish.mock.lastCall![0]).toMatchObject({ loading: false, error: '切面分析失败，请稍后重试' });
  });

  it('rejects unknown statuses instead of rendering them as results', async () => {
    const publish = vi.fn();
    await createEventAngleAnalysisController(8, vi.fn().mockResolvedValue({ status: 'garbage' }), publish).run();
    const last = publish.mock.lastCall![0] as AngleAnalysisState;
    expect(last.analysis).toBeNull();
    expect(last.error).toContain('未知状态');
  });

  it('re-runs on demand (刷新即重算) and never caches locally', async () => {
    const fetchAnalysis = vi.fn().mockResolvedValue(analysis);
    const controller = createEventAngleAnalysisController(8, fetchAnalysis, vi.fn());

    await controller.run();
    await controller.run();
    expect(fetchAnalysis).toHaveBeenCalledTimes(2);
  });

  it('does not send a second request for a rapid double click', async () => {
    const pending = deferred<EventAngleAnalysis>();
    const fetchAnalysis = vi.fn(() => pending.promise);
    const controller = createEventAngleAnalysisController(8, fetchAnalysis, vi.fn());

    const first = controller.run();
    await controller.run();
    expect(fetchAnalysis).toHaveBeenCalledTimes(1);
    pending.resolve(analysis);
    await first;
  });

  it.each(['resolve', 'reject'] as const)('ignores late %s after the panel is collapsed', async (outcome) => {
    const pending = deferred<EventAngleAnalysis>();
    const publish = vi.fn();
    const controller = createEventAngleAnalysisController(8, () => pending.promise, publish);
    const running = controller.run();
    controller.cancel();
    const callsBefore = publish.mock.calls.length;
    if (outcome === 'resolve') pending.resolve(analysis);
    else pending.reject(new Error('late failure'));
    await running;
    expect(publish).toHaveBeenCalledTimes(callsBefore);
  });

  it('passes the displayed report id to the fetcher', async () => {
    const fetchAnalysis = vi.fn().mockResolvedValue(analysis);
    await createEventAngleAnalysisController(42, fetchAnalysis, vi.fn()).run();
    expect(fetchAnalysis).toHaveBeenCalledWith(42);
  });
});

describe('angleRefHref', () => {
  it('links references to the in-site reader page', () => {
    expect(angleRefHref({ content_id: 7 })).toBe('/contents/7/reader');
  });
});
