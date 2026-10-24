import type { ContentEventCoverage, ContentNormalizationSummary } from '@/types';

export interface CoveragePageParams {
  member_offset: number;
  member_limit: number;
  expected_event_id?: number;
  expected_version?: number;
}

export interface CoverageState {
  coverage: ContentNormalizationSummary | null;
  loading: boolean;
  error: string | null;
  changed: boolean;
}

type CoverageFetcher = (id: number, params: CoveragePageParams) => Promise<{
  content_id: number;
  event: ContentEventCoverage | null;
}>;

/** A displayed report owns its requests, offsets and event version. */
export function createEventCoverageLoader(
  contentId: number,
  seed: ContentNormalizationSummary,
  fetchPage: CoverageFetcher,
  publish: (state: CoverageState) => void,
) {
  let sequence = 0;
  let disposed = false;
  let state: CoverageState = { coverage: seed, loading: false, error: null, changed: false };
  const emit = (patch: Partial<CoverageState>) => {
    state = { ...state, ...patch };
    publish(state);
  };

  return {
    cancel() { disposed = true; sequence += 1; },
    async loadMore() {
      if (disposed || state.loading) return;
      const current = ++sequence;
      const active = () => !disposed && sequence === current;
      const previous = state.coverage;
      // Legacy cached summaries have no event/version. Start a fresh page
      // instead of appending using an offset with unknown ownership.
      const canAppend = previous?.event_id !== undefined && previous.version !== undefined;
      const params: CoveragePageParams = {
        member_offset: canAppend ? (previous.next_offset ?? previous.members.length) : 0,
        member_limit: 20,
        ...(canAppend ? { expected_event_id: previous.event_id, expected_version: previous.version } : {}),
      };
      emit({ loading: true, error: null });
      try {
        let response;
        let append = canAppend;
        try {
          response = await fetchPage(contentId, params);
        } catch (error) {
          if (!active()) return;
          if ((error as { status?: number })?.status !== 409) throw error;
          append = false;
          emit({ coverage: null, changed: true });
          response = await fetchPage(contentId, { member_offset: 0, member_limit: 20 });
        }
        if (!active()) return;
        if (response.content_id !== contentId) throw new Error('报道已切换，请重新展开');
        const page = response.event;
        if (!page) {
          emit({ coverage: null, changed: true });
          return;
        }
        if (page.representative_id !== contentId) throw new Error('报道已切换，请重新展开');
        if (append && previous && (
          page.event_id !== previous.event_id || page.version !== previous.version
          || page.member_offset !== params.member_offset
        )) throw new Error('报道分组已变化，请刷新页面后重试');
        if ((!append && page.member_offset !== 0)
          || page.next_offset !== page.member_offset + page.members.length
          || (page.has_more && page.next_offset <= page.member_offset)) {
          throw new Error('报道列表暂时无法继续加载，请重试');
        }
        const members = append && previous ? [...previous.members, ...page.members] : page.members;
        if (members.some(member => member.id === contentId)
          || new Set(members.map(member => member.id)).size !== members.length) {
          throw new Error('报道列表已变化，请刷新页面后重试');
        }
        emit({ coverage: { ...page, member_offset: 0, members } });
      } catch {
        if (active()) emit({ error: '其它报道加载失败，请重试' });
      } finally {
        if (active()) emit({ loading: false });
      }
    },
  };
}
