'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, ExternalLink, Layers3, Loader2 } from 'lucide-react';
import { contentsApi } from '@/lib/api';
import { timeAgo } from '@/lib/datetime';
import { createEventCoverageLoader } from '@/lib/event-coverage';
import type { CoverageState } from '@/lib/event-coverage';
import type { ContentItem, ContentNormalizationMember, ContentNormalizationSummary } from '@/types';

const RELATIONS: Record<ContentNormalizationMember['relation_type'], { label: string; className: string }> = {
  canonical: { label: '原始主报道', className: 'bg-gray-100 text-gray-600' },
  duplicate: { label: '同事件报道', className: 'bg-gray-100 text-gray-600' },
  corroboration: { label: '补充报道', className: 'bg-teal/10 text-teal-text' },
  update: { label: '后续进展', className: 'bg-amber-50 text-amber-700' },
};

function CoverageDisclosure({ contentId, seed }: { contentId: number; seed: ContentNormalizationSummary }) {
  const [expanded, setExpanded] = useState(false);
  const [state, setState] = useState<CoverageState>({ coverage: seed, loading: false, error: null, changed: false });
  const [initialSeed] = useState(seed);
  const loader = useRef<ReturnType<typeof createEventCoverageLoader> | null>(null);
  const disclosureId = useId();
  useEffect(() => {
    const current = createEventCoverageLoader(contentId, initialSeed, contentsApi.getEventCoverage, setState);
    loader.current = current;
    return () => { current.cancel(); loader.current = null; };
  }, [contentId, initialSeed]);
  const coverage = state.coverage;
  const members = coverage?.members ?? [];
  const hasUpdates = (coverage?.update_count ?? 0) > 0 || members.some(member => member.relation_type === 'update');

  return (
    <div className="mb-3" onClick={event => event.stopPropagation()}>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={disclosureId}
        onClick={() => {
          setExpanded(current => !current);
          if (!expanded && !members.length && coverage?.member_count) void loader.current?.loadMore();
        }}
        className="inline-flex min-h-9 max-w-full items-center gap-1.5 rounded-xs border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-left text-xs font-semibold text-gray-600 transition hover:border-primary-border hover:bg-primary-light hover:text-primary-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      >
        <Layers3 size={14} className="shrink-0" aria-hidden="true" />
        <span className="min-w-0">
          {coverage ? `另有 ${coverage.member_count} 篇报道 · 共 ${coverage.source_count} 个来源` : '报道分组已更新'}
          {hasUpdates && <span className="ml-1.5 inline-block whitespace-nowrap text-amber-700">有后续进展</span>}
        </span>
        {expanded ? <ChevronUp size={14} className="shrink-0" /> : <ChevronDown size={14} className="shrink-0" />}
      </button>

      {expanded && (
        <div id={disclosureId} className="mt-2 rounded-sm border border-gray-200 bg-[#FBFCFE]" aria-label="同一事件的其它报道" aria-busy={state.loading}>
          {state.changed && <p className="px-3 pt-3 text-xs text-gray-500" role="status">{state.loading ? '报道分组已变化，正在重新加载…' : state.error ? '报道分组已变化，请重试加载。' : '报道分组已更新。'}</p>}
          <ul className="divide-y divide-gray-100">
            {members.map(member => {
              const relation = RELATIONS[member.relation_type] ?? RELATIONS.duplicate;
              const timestamp = member.published_at || member.crawled_at;
              return (
                <li key={member.id} className="px-3 py-3">
                  <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                    <span className={`rounded px-1.5 py-0.5 font-medium ${relation.className}`}>{relation.label}</span>
                    <span className="text-gray-600">{member.source_name || '未知来源'}</span>
                    {timestamp && <time dateTime={timestamp} className="text-gray-500">{timeAgo(timestamp)}</time>}
                  </div>
                  <div className="flex items-start justify-between gap-3">
                    <a href={`/contents/${member.id}/reader`} className="min-w-0 text-sm font-medium leading-6 text-gray-800 hover:text-primary-text hover:underline">
                      {member.title}
                    </a>
                    {member.url && (
                      <a href={member.url} target="_blank" rel="noopener noreferrer" aria-label={`打开原文：${member.title}`} className="inline-flex min-h-8 shrink-0 items-center gap-1 text-xs font-semibold text-teal-text hover:underline">
                        原文 <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
          {!members.length && !state.loading && !state.error && <p className="px-3 py-3 text-sm text-gray-600">当前没有其它同事件报道。</p>}
          {(coverage?.has_more || state.error || state.loading) && (
            <div className="border-t border-gray-100 px-3 py-2">
              {state.error && <p className="mb-1 text-xs text-red" role="alert">{state.error}</p>}
              <button type="button" disabled={state.loading} onClick={() => void loader.current?.loadMore()} className="inline-flex min-h-9 items-center gap-1.5 text-xs font-semibold text-primary-text hover:underline disabled:opacity-60">
                {state.loading && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
                {state.loading ? '加载中…' : state.error ? '重试加载其它报道' : `查看其余 ${Math.max(0, (coverage?.member_count ?? 0) - members.length)} 篇报道`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function EventCoverage({ item }: { item: Pick<ContentItem, 'id' | 'normalization'> }) {
  const seed = item.normalization;
  if (!seed || seed.member_count <= 0) return null;
  return <CoverageDisclosure key={`${item.id}:${seed.event_id ?? seed.canonical_id}:${seed.version ?? 0}`} contentId={item.id} seed={seed} />;
}
