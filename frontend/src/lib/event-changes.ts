import type { EventChangeAnalysis, EventChangeRequest } from '@/types/event-changes';

export interface EventChangeState {
  analysis: EventChangeAnalysis | null;
  loading: boolean;
  error: string | null;
  conflict: boolean;
}
const KINDS = new Set(['no_new_material', 'fact', 'evidence', 'opinion', 'uncertain']);

export function createEventChangeController(
  contentId: number,
  snapshot: EventChangeRequest,
  fetcher: (id: number, request: EventChangeRequest) => Promise<EventChangeAnalysis>,
  publish: (state: EventChangeState) => void,
) {
  // Request, validation and final callbacks consume the same immutable identity.
  const request = { ...snapshot, member_ids: [...snapshot.member_ids] };
  let disposed = false;
  let sequence = 0;
  let state: EventChangeState = { analysis: null, loading: false, error: null, conflict: false };
  const emit = (patch: Partial<EventChangeState>) => { state = { ...state, ...patch }; publish(state); };
  return {
    cancel() { disposed = true; sequence += 1; },
    async run() {
      if (disposed || state.loading || state.conflict) return;
      const current = ++sequence;
      const active = () => !disposed && current === sequence;
      emit({ loading: true, error: null, analysis: null });
      try {
        const result = await fetcher(contentId, { ...request, member_ids: [...request.member_ids] });
        if (!active()) return;
        if (!result || result.anchor?.id !== contentId || result.event_id !== request.expected_event_id
          || result.version !== request.expected_version || !Array.isArray(result.member_ids)
          || result.member_ids.join(',') !== request.member_ids.join(',') || !Array.isArray(result.items)
          || result.items.length !== request.member_ids.length || !['ok', 'partial', 'insufficient_material'].includes(result.status)
          || result.items.some((item, index) => item.id !== request.member_ids[index] || !KINDS.has(item.change_type)
            || typeof item.description !== 'string' || !Array.isArray(item.quotes)
            || (item.change_type !== 'uncertain' && (item.quotes.length !== 2 || new Set(item.quotes.map(ref => ref.id)).size !== 2))
            || item.quotes.some(ref => ![contentId, item.id].includes(ref.id) || typeof ref.excerpt !== 'string'))) {
          throw new Error('对照结果与当前报道不一致，请重新加载报道');
        }
        emit({ analysis: result });
      } catch (error) {
        if (active()) emit({ error: error instanceof Error ? error.message : '变化对照失败，请重试', conflict: (error as { status?: number })?.status === 409 });
      } finally {
        if (active()) emit({ loading: false });
      }
    },
  };
}

export function relationFeedbackPayload(memberId: number, eventId: number, version: number, reason: string) {
  const trimmed = reason.trim();
  if (trimmed.length < 5 || trimmed.length > 1500) throw new Error('请用 5–1500 个字说明关联哪里有误');
  return { expected_event_id: eventId, expected_version: version, member_id: memberId, reason: trimmed };
}
