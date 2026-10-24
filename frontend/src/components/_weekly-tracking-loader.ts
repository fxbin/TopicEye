import type { weeklyDigestApi } from '@/lib/api';
import { createRequestGuard } from '@/lib/request-guard';

export type WeeklyTrackingData = Awaited<ReturnType<typeof weeklyDigestApi.pickTracking>>;

export function createWeeklyTrackingLoader(
  fetch: (weekKey: string) => Promise<WeeklyTrackingData>,
  state: { data(value: WeeklyTrackingData | null): void; pending(value: boolean): void; error(value: string | null): void },
) {
  const guard = createRequestGuard();
  return {
    cancel: () => guard.invalidate(),
    async load(weekKey?: string) {
      const active = guard.begin();
      state.data(null);
      state.error(null);
      state.pending(Boolean(weekKey));
      if (!weekKey) return;
      try {
        const data = await fetch(weekKey);
        if (active()) state.data(data);
      } catch (err) {
        if (active()) state.error(err instanceof Error ? err.message : '选题追踪加载失败，请重试');
      } finally {
        if (active()) state.pending(false);
      }
    },
  };
}
