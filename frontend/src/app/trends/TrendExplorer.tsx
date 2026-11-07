'use client';

import React, { useEffect, useRef, useState } from 'react';
import { ArrowDownRight, ArrowUpRight, ArrowRight, RefreshCw } from 'lucide-react';
import { Button, cx } from '@/components/ui';
import { EmptyState, ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { trendsApi } from '@/lib/api';
import type { TrendKeywordItem, TrendEvidenceRequest } from '@/types/trends';
import TrendEvidenceDrawer from './TrendEvidenceDrawer';
import { buildTrendModel } from './_trend-model';
import TopicMaterials from './TopicMaterials';
import TitleText from './_title-text';
import styles from './page.module.css';
import KeywordIndex from './KeywordIndex';
import keywordStyles from './_keyword-index.module.css';

type View = 'topics' | 'keywords';
const WINDOWS = [3, 7, 14, 30];
const dateLabel = (date: string) => date.replaceAll('-', '/');

export default function TrendExplorer({ view, days, onDaysChange, onReady, initialLimit = 15, onLimitChange }: { view: View; days: number; onDaysChange: (days: number) => void; onReady?: () => void; initialLimit?: number; onLimitChange?: (limit: number) => void }) {
  const [limit, setLimit] = useState(initialLimit);
  const [entered, setEntered] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<number | null>(null);
  const triggerRefs = useRef(new Map<number, HTMLButtonElement>());
  const [evidence, setEvidence] = useState<TrendEvidenceRequest | null>(null);
  const { data, loading, error, refetch } = useFetch(async () => {
    const scope = days;
    if (view === 'topics') return { days: scope, view, trends: (await trendsApi.topics(scope)).trends, keywords: [] };
    return { days: scope, view, trends: [], keywords: (await trendsApi.keywords({ days: scope, limit: 60 })).keywords };
  }, [days, view]);
  // A newly selected window must never borrow the previous window's numbers.
  const current = data?.days === days && data.view === view ? data : null;
  const busy = loading || (!current && !error);
  useEffect(() => { if (!busy && current) onReady?.(); }, [busy, current, onReady]);
  const model = buildTrendModel(current?.trends ?? []);
  const words: TrendKeywordItem[] = current?.keywords ?? [];
  const changeDays = (value: number) => { if (value === days) return; setSelectedTopic(null); setEvidence(null); setLimit(15); onDaysChange(value); };
  const shown = model.topics.slice(0, limit);
  const comparable = model.topics.filter(topic => topic.delta !== null).length;
  const openKeyword = (keyword: string) => setEvidence({ kind: 'keyword', keyword, days });
  const closeMaterials = (id: number) => {
    setSelectedTopic(null);
    requestAnimationFrame(() => { const trigger = triggerRefs.current.get(id); trigger?.focus({ preventScroll: true }); trigger?.scrollIntoView({ block: 'nearest', behavior: 'instant' }); });
  };
  const controls = (<div className={cx(styles.controls, view === 'keywords' && keywordStyles.controls, "mt-4 flex flex-wrap items-center justify-between gap-3")} aria-label="趋势筛选">
        <div role="group" aria-label="观察窗口" className="relative grid w-full grid-cols-4 rounded-sm bg-gray-100 p-1 sm:w-[280px]">
          <span aria-hidden className={cx(styles.indicator, 'absolute bottom-1 left-1 top-1 rounded-xs bg-white shadow-sm')} style={{ width: 'calc((100% - 8px) / 4)', transform: `translateX(${WINDOWS.indexOf(days) * 100}%)` }} />
          {WINDOWS.map(value => <button key={value} type="button" aria-pressed={days === value} onClick={() => changeDays(value)} className={cx(styles.press, 'relative min-h-9 rounded-xs px-3 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-primary', days === value ? 'text-primary-text' : 'text-gray-600')}>{value}天</button>)}
        </div>
        <Button variant="ghost" type="button" disabled={busy} onClick={() => { setSelectedTopic(null); void refetch(); }} className="min-h-9 text-xs"><RefreshCw size={14} className={busy ? 'animate-spin motion-reduce:animate-none' : ''} />刷新{view === 'topics' ? '材料' : '热词'}</Button>
      </div>);
  return <div className={styles.page}>
      {view === 'keywords' ? <header className={keywordStyles.header}><h2>高频热词</h2>{controls}</header> : controls}
      {view === 'keywords' ? <div className={keywordStyles.meta}>
        <p role="status">{busy ? `正在读取近 ${days} 天的高频热词…` : current ? <>近 {days} 天<span className={keywordStyles.dot}>·</span><span><b>{words.length}</b> 个关键词</span><span className={keywordStyles.dot}>·</span><span>按内容数排序</span></> : '尚未取得当前窗口数据'}</p>
        <details className={keywordStyles.help}><summary>统计说明</summary><p>来自公共收录内容的分析标签。数值为带有该标签的内容数，一条内容可对应多个关键词，计数不能相加。点击词条查看来源。</p></details>
      </div> : <div className={styles.edition}>
        <p role="status">{busy ? `正在读取近 ${days} 天的话题线索…` : model.latestDate ? `数据截至 ${dateLabel(model.latestDate)} · 近 ${days} 天有 ${model.recordedDays} 个记录日` : error ? '尚未取得当前窗口数据' : `近 ${days} 天暂无快照`}</p>
        {current && !busy && <p aria-label="话题快照统计"><b>{model.topics.length}</b> 个话题 <span> / </span><b>{model.totalContent}</b> 条收录 <span> / </span><b>{model.totalPicks}</b> 条入选</p>}
      </div>}
      {error && <div className="mt-3"><ErrorState error={error} onRetry={() => void refetch()} panel={false} />{current && <p className="text-xs text-gray-500">以下保留当前窗口上次成功读取的快照。</p>}</div>}
      {busy ? <LoadingState label="加载趋势快照…" minHeight="180px" /> : current && <div className={entered ? undefined : styles.enter} onAnimationEnd={() => setEntered(true)}>
        <section id="trends-topics-panel" aria-label="话题线索" hidden={view !== 'topics'} tabIndex={0}>
          <div className={styles.sectionHeading}><div><h2>话题线索</h2><p className="mt-2 text-xs leading-5 text-gray-600">公共收录，含未入选文章。</p></div><p>显示 {shown.length} / {model.topics.length} 个话题<br />{comparable ? '按动量排序' : '按收录与入选数排序'}</p></div>
          {!shown.length ? <EmptyState title="暂无话题快照" desc="快照生成后，可在这里查看话题与收录材料。" /> : <ol className={cx(styles.topicList, selectedTopic !== null && styles.focused)} style={{ '--topic-rows': shown.length } as React.CSSProperties}>
            {shown.map((topic, index) => {
              const latest = topic.pts.at(-1)!;
              const preview = latest.top_items?.[0];
              const active = selectedTopic === topic.topicId;
              return <li role="listitem" key={topic.topicId} className={styles.topicRow}>
                <button ref={node => { if (node) triggerRefs.current.set(topic.topicId, node); else triggerRefs.current.delete(topic.topicId); }} id={`topic-trigger-${topic.topicId}`} type="button" className={cx(styles.topicTrigger, active && styles.active)} aria-expanded={active} aria-controls={active ? `topic-materials-${topic.topicId}` : undefined} onClick={() => active ? closeMaterials(topic.topicId) : setSelectedTopic(topic.topicId)}>
                  <span className={styles.topicNumber}>{String(index + 1).padStart(2, '0')}</span>
                  <span className={styles.topicInfo}><span className={styles.topicName}>{topic.name}</span><span>{dateLabel(topic.latestDate)}</span><span>{topic.latestCount} 条收录 · {latest.pick_count} 条入选</span></span>
                  <span className={styles.topicPreview}><span className={styles.previewTitle}><TitleText title={preview?.title || '本次快照暂无文章节选'} /></span><span className={styles.previewCaption}>{preview ? '最新快照 · 首条节选' : '展开查看现存材料'}<span className={styles.comparison}>{topic.delta === null ? (topic.pts.length === 1 ? '仅一次快照，暂无法比较' : '记录间断或口径不同，暂无法比较') : <>{topic.delta > 0 ? <ArrowUpRight size={13} /> : topic.delta < 0 ? <ArrowDownRight size={13} /> : null}{dateLabel(topic.latestDate)} 较 {dateLabel(topic.previousDate!)} {topic.delta === 0 ? '持平' : `${topic.delta > 0 ? '+' : ''}${topic.delta}条`}</>}</span></span></span>
                  <ArrowRight size={20} className={styles.rowArrow} aria-hidden />
                </button>
                {active && <div className={styles.detailSlot}><TopicMaterials key={`${days}:${topic.topicId}:${topic.pts.map(point => `${point.date}:${point.snapshot_id ?? ''}:${point.content_count}`).join(',')}`} topic={topic} onClose={() => closeMaterials(topic.topicId)} /></div>}
              </li>;
            })}
          </ol>}
          {shown.length < model.topics.length && <Button variant="secondary" type="button" onClick={() => { setLimit(model.topics.length); onLimitChange?.(model.topics.length); }} className="mt-3 w-full">查看其余 {model.topics.length - shown.length} 个话题</Button>}
        </section>
        <section id="trends-keywords-panel" aria-label="高频热词" hidden={view !== 'keywords'} tabIndex={0}>
          {!words.length ? <EmptyState title="暂无关键词数据" desc="关键词快照生成后会在这里展示。" /> : <KeywordIndex words={words} selectedKeyword={evidence?.kind === 'keyword' ? evidence.keyword : null} onSelect={openKeyword} />}
        </section>
      </div>}
    <TrendEvidenceDrawer request={evidence} onClose={() => setEvidence(null)} />
  </div>;
}
