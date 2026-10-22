import { describe, expect, it, vi } from 'vitest';
import { createReportLoader } from './_report-loader';
import type { DailyReportData } from './_daily-utils';
import type { YesterdayTrackingData } from '@/types';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const report = (date: string) => ({ report_date: date, top_picks: [{ title: 'same topic' }, { title: 'same topic' }] }) as DailyReportData;
const tracking = { has_yesterday: false, picks: [], your_marked: [] } as unknown as YesterdayTrackingData;
function setup() {
  const api = {
    report: vi.fn(async (date?: string) => report(date!)),
    marks: vi.fn(async () => ({ marks: [] })),
    tracking: vi.fn(async () => tracking),
    sparkline: vi.fn(async () => ({ points: [], keywords: [], total: 0, window_hours: 48 })),
  };
  const sink = { report: vi.fn(), marks: vi.fn(), tracking: vi.fn(), sparkline: vi.fn(), loaded: vi.fn(), error: vi.fn() };
  return { api, sink, loader: createReportLoader(api, sink) };
}

describe('daily navigation response ownership', () => {
  it('ignores an older report that arrives after a newer date', async () => {
    const { api, sink, loader } = setup();
    const old = deferred<DailyReportData>();
    api.report.mockImplementationOnce(() => old.promise);
    const first = loader.load('2026-10-20');
    await loader.load('2026-10-21');
    old.resolve(report('2026-10-20'));
    await first;
    expect(sink.report.mock.calls.map(([r]) => r.report_date)).toEqual(['2026-10-21']);
    expect(api.marks).toHaveBeenCalledTimes(1);
    expect(sink.loaded).toHaveBeenCalledTimes(1);
  });

  it('ignores old marks and tracking after the user changes dates', async () => {
    const { api, sink, loader } = setup();
    const oldMarks = deferred<{ marks: [] }>();
    const oldTracking = deferred<YesterdayTrackingData>();
    api.marks.mockImplementationOnce(() => oldMarks.promise);
    api.tracking.mockImplementationOnce(() => oldTracking.promise);
    const first = loader.load('2026-10-20');
    await vi.waitFor(() => expect(api.marks).toHaveBeenCalledTimes(1));
    await loader.load('2026-10-21');
    oldMarks.resolve({ marks: [] }); oldTracking.resolve(tracking);
    await first;
    expect(sink.marks).toHaveBeenCalledTimes(1);
    expect(sink.tracking).toHaveBeenCalledTimes(1);
  });

  it('unblocks reading before slow charts and deduplicates titles', async () => {
    const { api, sink, loader } = setup();
    const slow = deferred<Awaited<ReturnType<typeof api.sparkline>>>();
    api.sparkline.mockImplementation(() => slow.promise);
    const loading = loader.load('2026-10-21');
    await vi.waitFor(() => expect(sink.loaded).toHaveBeenCalledOnce());
    expect(sink.report).toHaveBeenCalledOnce();
    expect(api.sparkline).toHaveBeenCalledTimes(1);
    slow.resolve({ points: [], keywords: [], total: 0, window_hours: 48 });
    await loading;
  });

  it('cancels all late updates on unmount, including errors', async () => {
    const { api, sink, loader } = setup();
    const pending = deferred<DailyReportData>();
    api.report.mockImplementation(() => pending.promise);
    const loading = loader.load('2026-10-21');
    loader.cancel(); pending.reject(new Error('network failed'));
    await loading;
    expect(sink.error).not.toHaveBeenCalled();
    expect(sink.loaded).not.toHaveBeenCalled();
  });

  it('keeps the report readable when optional data fails and settles tracking', async () => {
    const { api, sink, loader } = setup();
    api.marks.mockRejectedValue(new Error('offline'));
    api.tracking.mockRejectedValue(new Error('offline'));
    await loader.load('2026-10-21');
    expect(sink.report).toHaveBeenCalledOnce();
    expect(sink.error).not.toHaveBeenCalled();
    expect(sink.tracking).toHaveBeenCalledWith(null);
  });

  it('displays the generated version rather than refetching an older preferred final edition', async () => {
    const { api, sink, loader } = setup();
    const generated = { ...report('2026-10-21'), id: 136 };
    await loader.load('2026-10-21', generated);
    expect(api.report).not.toHaveBeenCalled();
    expect(sink.report).toHaveBeenCalledWith(generated);
  });
});
