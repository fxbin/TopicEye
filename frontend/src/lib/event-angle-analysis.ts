import type { EventAngleAnalysis } from '@/types';

export interface AngleAnalysisState {
  analysis: EventAngleAnalysis | null;
  loading: boolean;
  error: string | null;
}

type AnalysisFetcher = (id: number) => Promise<EventAngleAnalysis>;

/**
 * 切面分析控制器：每次点击都重新请求（「刷新即重算」），不落任何本地持久化。
 *
 * 与 createEventCoverageLoader 同构：请求所有权归组件实例，
 * 卸载后迟到响应不再发布；loading 中的重复点击不发第二个请求。
 * 错误显式抛给 UI（不安静吞错），重试就是再点一次按钮。
 */
export function createEventAngleAnalysisController(
  contentId: number,
  fetchAnalysis: AnalysisFetcher,
  publish: (state: AngleAnalysisState) => void,
) {
  let sequence = 0;
  let disposed = false;
  let state: AngleAnalysisState = { analysis: null, loading: false, error: null };
  const emit = (patch: Partial<AngleAnalysisState>) => {
    state = { ...state, ...patch };
    publish(state);
  };

  return {
    cancel() {
      disposed = true;
      sequence += 1;
    },
    get state(): AngleAnalysisState {
      return state;
    },
    async run() {
      if (disposed || state.loading) return;
      const current = ++sequence;
      const active = () => !disposed && sequence === current;
      emit({ loading: true, error: null });
      try {
        const analysis = await fetchAnalysis(contentId);
        if (!active()) return;
        if (analysis.status !== 'ok' && analysis.status !== 'no_event') {
          throw new Error('切面分析返回了未知状态，请稍后重试');
        }
        emit({ analysis });
      } catch (error) {
        if (!active()) return;
        const message = error instanceof Error && error.message ? error.message : '';
        emit({ error: message || '切面分析失败，请稍后重试' });
      } finally {
        if (active()) emit({ loading: false });
      }
    },
  };
}

/** 稀缺角度引用的站内阅读页地址（与 EventCoverage 的成员跳转同一路径）。 */
export function angleRefHref(ref: { content_id: number }): string {
  return `/contents/${ref.content_id}/reader`;
}
