'use client';

import React, { useState } from 'react';
import { ArrowUpRight, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import EvidenceTag from '@/components/EvidenceTag';
import SourceBadge from '@/components/SourceBadge';
import SourceLink from '@/components/SourceLink';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { trendsApi } from '@/lib/api';
import type { TrendEvidenceFilter } from '@/types/trends';
import type { TopicSeries } from './_trend-model';
import styles from './page.module.css';
import TitleText from './_title-text';

const FILTERS = [['all', '全部'], ['selected', '已入选'], ['evidenced', '有来源证据']] as const;

// Remount on topic/date/filter. Within that identity, keep pagination controls mounted.
// Page-tagged results hide old rows while the next page loads.
export function MaterialPage({ topicId, date, filter, page, setPage }: { topicId: number; date: string; filter: TrendEvidenceFilter; page: number; setPage: (page: number) => void }) {
  const { openReader } = useAppContext();
  const { data: result, loading, error, refetch } = useFetch(async () => ({ page, payload: await trendsApi.topicEvidence(topicId, date, { filter, page, page_size: 20 }) }), [page]);
  const data = result?.page === page ? result.payload : null;
  const busy = loading || (!data && !error);
  const complete = data?.summary.provenance_status === 'complete';
  const total = result?.payload.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 20));
  const retry = () => {
    const region = document.getElementById(`topic-materials-${topicId}`);
    const restoreFocus = !!document.activeElement?.closest('[role="alert"]');
    void refetch().then(() => requestAnimationFrame(() => {
      // Retrying removes the error button. Restore only if focus was lost there;
      // do not steal focus after the reader moves to another control or topic.
      if (restoreFocus && region?.isConnected && document.activeElement === document.body) {
        const retryButton = region.querySelector<HTMLButtonElement>('[role="alert"] button');
        (retryButton ?? region).focus({ preventScroll: true });
      }
    }));
  };
  return <>
    {busy ? <LoadingState label="正在读取这次快照的材料…" minHeight="160px" /> : error ? <ErrorState error={error} onRetry={retry} panel={false} /> : data && <>
    <div className={styles.snapshotNotice}>
      <p>{complete ? '已保留完整成员记录' : '历史成员记录不完整'} · {data.summary.source_count} 个信源</p>
      <p>{filter === 'all' ? '当前可查看' : '当前筛选可查看'} <b>{data.total}</b> 条{!complete && <> · 历史收录 {data.daily_counts?.find(point => point.date === date)?.count ?? data.summary.content_count} 条</>}</p>
      {(!complete || data.calculation.event_members_excluded) && <details className={styles.recordDetails}><summary>查看记录说明</summary>{!complete && <p>{data.message || '以下仅为现存材料，不能还原当时全部内容。'}</p>}{data.calculation.event_members_excluded && <p>已排除已合并事件成员。</p>}</details>}
    </div>
    {data.items.length ? <ol className={styles.materialList}>{data.items.map((item, index) => {
      const time = item.time_basis === 'published_at' ? item.published_at : item.crawled_at;
      return <li key={`${item.content_id ?? item.url ?? item.title}:${index}`}>
        <span className={styles.materialNumber}>{String((page - 1) * 20 + index + 1).padStart(2, '0')}</span>
        <div className={styles.materialBody}>
          {item.content_id ? <button type="button" className={styles.materialTitle} onClick={() => openReader(item.content_id!)} title="站内阅读"><TitleText title={item.title} /></button> : <h4 className={styles.materialTitle}><TitleText title={item.title} /></h4>}
          <div className={styles.materialMeta}><SourceBadge name={item.source_name} type={item.source_type} compact fallback={item.platform || undefined} />{time && <span>{item.time_basis === 'published_at' ? '发布' : '抓取'} {time.replace('T', ' ').slice(0, 16)}</span>}</div>
          <div className={styles.materialActions}>{item.selected && <span>已入选</span>}<EvidenceTag mark={item.evidence_mark} />{typeof item.score === 'number' && <span>评分 {Math.round(item.score)}</span>}{item.url && <SourceLink href={item.url} target="_blank" rel="noopener noreferrer">原文 <ArrowUpRight size={13} aria-hidden /></SourceLink>}</div>
        </div>
      </li>;
    })}</ol> : <p className={styles.noMaterials}>这次快照中没有符合筛选条件的材料。</p>}
    </>}
    {total > 0 && <nav aria-label="话题材料分页" className={styles.pagination}><span aria-live="polite">共 {total} 条 · {page} / {pages} 页{busy ? ' · 读取中' : ''}</span><div><button type="button" aria-disabled={page === 1 || busy} onClick={() => { if (page > 1 && !busy) setPage(page - 1); }} aria-label="上一页材料"><ChevronLeft size={16} /></button><button type="button" aria-disabled={page >= pages || busy} onClick={() => { if (page < pages && !busy) setPage(page + 1); }} aria-label="下一页材料"><ChevronRight size={16} /></button></div></nav>}
  </>;
}

export default function TopicMaterials({ topic, onClose }: { topic: TopicSeries; onClose: () => void }) {
  const [date, setDate] = useState(topic.latestDate);
  const [filter, setFilter] = useState<TrendEvidenceFilter>('all');
  const [page, setPage] = useState(1);
  const selected = topic.pts.find(point => point.date === date) ?? topic.pts.at(-1)!;
  return <section id={`topic-materials-${topic.topicId}`} className={styles.materials} tabIndex={-1} aria-label={`${topic.name}的材料`} onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose(); } }}>
    <header className={styles.materialHeader}><div><h3>{topic.name}</h3></div><button type="button" onClick={onClose} className={styles.close} aria-label="收起话题材料"><X size={18} /></button></header>
    <div className={styles.snapshotBar}><label>快照日期 <select aria-label={`${topic.name}的快照日期`} value={selected.date} onChange={event => { setDate(event.target.value); setFilter('all'); setPage(1); }}>{topic.pts.map(point => <option key={point.date} value={point.date}>{point.date.replaceAll('-', '/')}</option>)}</select></label><span>{selected.content_count} 条收录</span></div>
    <p className={styles.groupNotice}>同一话题的收录，可能涉及不同事件。</p>
    <div className={styles.materialFilters} role="group" aria-label="话题材料筛选">{FILTERS.map(([value, label]) => <button key={value} type="button" aria-pressed={filter === value} onClick={() => { setFilter(value); setPage(1); }}>{label}</button>)}</div>
    <MaterialPage key={`${topic.topicId}:${selected.date}:${filter}`} topicId={topic.topicId} date={selected.date} filter={filter} page={page} setPage={setPage} />
  </section>;
}
