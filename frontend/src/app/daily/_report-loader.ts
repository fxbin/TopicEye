import type { DailyReportData, MarkAction } from './_daily-utils';
import { marksMapFromResp, parseJson, pickKey } from './_daily-utils';
import type { SparklineData } from '@/components/Sparkline';
import type { YesterdayTrackingData } from '@/types';

interface ReportApi {
  report(date?: string): Promise<DailyReportData>;
  marks(date: string): Promise<{ marks: Array<{ pick_title: string; action: MarkAction }> }>;
  tracking(date: string): Promise<YesterdayTrackingData>;
  sparkline(title: string): Promise<SparklineData>;
}
interface ReportSink {
  report(data: DailyReportData): void;
  marks(data: Record<string, MarkAction>): void;
  tracking(data: YesterdayTrackingData | null): void;
  sparkline(key: string, data: SparklineData): void;
  loaded(): void;
  error(error: unknown): void;
}

/** One navigation owns every response, including late marks and trend data. */
export function createReportLoader(api: ReportApi, sink: ReportSink) {
  let sequence = 0;
  return {
    cancel() { sequence += 1; },
    async load(date?: string, knownReport?: DailyReportData) {
      const current = ++sequence;
      const active = () => sequence === current;
      try {
        const report = knownReport || await api.report(date);
        if (!active()) return;
        sink.report(report);
        sink.loaded(); // Reading does not wait for marks or charts.
        const picks = parseJson(report.top_picks);
        const keys = Array.isArray(picks)
          ? [...new Set(picks.map(pickKey).filter(Boolean))] : [];
        await Promise.allSettled([
          api.marks(report.report_date).then((data) => {
            if (active()) sink.marks(marksMapFromResp(data.marks));
          }),
          api.tracking(report.report_date).then((data) => {
            if (active()) sink.tracking(data);
          }).catch(() => { if (active()) sink.tracking(null); }),
          ...keys.map(async (key) => {
            const data = await api.sparkline(key);
            if (active()) sink.sparkline(key, data);
          }),
        ]);
      } catch (error) {
        if (active()) {
          sink.error(error);
          sink.loaded();
        }
      }
    },
  };
}
