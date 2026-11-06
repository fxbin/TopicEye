'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { contentsApi } from '@/lib/api';
import { useAuthContext } from '@/providers/AppProvider';
import { useReaderContext } from '@/providers/ReaderProvider';
import { createEventChangeController, type EventChangeState } from '@/lib/event-changes';
import type { EventChangeAnalysis, EventChangeItem } from '@/types/event-changes';
import type { ContentNormalizationSummary } from '@/types';

const LABELS = { no_new_material: '未见新增材料', fact: '事实进展线索', evidence: '新增证据材料', opinion: '新增观点', uncertain: '暂无法判断' };
export function EvidenceReaderLink({ id, children }: { id: number; children: ReactNode }) {
  const { openReader } = useReaderContext();
  return <Link href={`/contents/${id}/reader`} onClick={event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    openReader(id);
  }} className="text-xs text-teal-text hover:underline">{children}</Link>;
}

export function ChangeEvidence({ item }: { item?: EventChangeItem }) {
  if (!item) return null;
  return <div className="mt-2 space-y-1.5 text-[13px] leading-6 text-gray-600">
    <p className="break-words [overflow-wrap:anywhere]"><span className="mr-2 font-semibold text-gray-700">{LABELS[item.change_type]}</span>{item.description}</p>
    {item.quotes.length > 0 && <details>
      <summary className="w-fit cursor-pointer rounded-xs text-xs font-medium text-teal-text focus-visible:outline-2 focus-visible:outline-primary">查看原文依据</summary>
      <div className="mt-2 space-y-2 border-l-2 border-gray-200 pl-3">
        {item.quotes.map(ref => <blockquote key={ref.id} className="break-words [overflow-wrap:anywhere]">
          <p className="whitespace-pre-wrap">“{ref.excerpt}”</p>
          <EvidenceReaderLink id={ref.id}>{ref.source_name || '未知来源'} · {ref.title}</EvidenceReaderLink>
        </blockquote>)}
      </div>
    </details>}
  </div>;
}

interface Props {
  contentId: number;
  coverage: ContentNormalizationSummary;
  reload: () => void;
  children: (analysis: EventChangeAnalysis | null) => ReactNode;
}
export default function EventChangeComparison(props: Props) {
  const { currentUser } = useAuthContext();
  const ids = props.coverage.members.slice(0, 10).map(row => row.id);
  const identity = [currentUser?.id ?? 'guest', props.contentId, props.coverage.event_id, props.coverage.version, ids.join(',')].join(':');
  return <ComparisonWorkspace key={identity} {...props} loggedIn={!!currentUser} ids={ids} />;
}

function ComparisonWorkspace({ contentId, coverage, reload, children, loggedIn, ids }: Props & { loggedIn: boolean; ids: number[] }) {
  const pathname = usePathname();
  const [state, setState] = useState<EventChangeState>({ analysis: null, loading: false, error: null, conflict: false });
  const controller = useRef<ReturnType<typeof createEventChangeController> | null>(null);
  const ready = coverage.event_id !== undefined && coverage.version !== undefined && ids.length > 0;
  useEffect(() => {
    if (!ready) return;
    const value = createEventChangeController(contentId, { expected_event_id: coverage.event_id!, expected_version: coverage.version!, member_ids: ids }, contentsApi.analyzeEventChanges, setState);
    controller.current = value;
    return () => { value.cancel(); controller.current = null; };
    // Component key freezes content/event/version/member/user identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <>
    <section className="border-b border-gray-100 px-3 py-3" aria-label="报道变化对照" aria-busy={state.loading}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] font-semibold text-gray-700">这些报道新增了什么</span>
        {loggedIn ? <button type="button" disabled={!ready || state.loading || state.conflict} onClick={() => void controller.current?.run()} className="inline-flex min-h-9 items-center gap-1 rounded-xs px-2 text-xs font-semibold text-primary-text hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50">
          {state.loading && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}{state.loading ? '正在对照…' : state.error ? '重试对照' : state.analysis ? '重新对照' : 'AI 对照变化'}
        </button> : <Link href={`/login?returnTo=${encodeURIComponent(pathname)}`} className="text-xs font-semibold text-primary-text hover:underline">登录后对照变化</Link>}
      </div>
      <p className="mt-1 text-xs leading-5 text-gray-500">以当前报道为对照，比较已展开的前 {ids.length} 篇，最多 10 篇。对照限于材料片段，请结合原文判断。</p>
      {!ready && <button type="button" onClick={reload} className="mt-1 min-h-9 text-xs text-primary-text hover:underline">重新加载报道后再对照</button>}
      {state.error && <div className="mt-2 text-xs text-red" role="alert">{state.error}{state.conflict && <button type="button" onClick={reload} className="ml-2 min-h-9 underline">重新加载报道</button>}</div>}
      {state.analysis && <p className="mt-2 text-xs leading-5 text-gray-500" role="status">
        对照报道：<EvidenceReaderLink id={state.analysis.anchor.id}>{state.analysis.anchor.title}</EvidenceReaderLink>
        {state.analysis.status === 'partial' && <span className="block">部分材料未能核对，已标为暂无法判断。</span>}
        {state.analysis.status === 'insufficient_material' && <span className="block">正文片段不足，暂时无法对照；仍可打开原文。</span>}
      </p>}
    </section>
    {children(state.analysis)}
  </>;
}
