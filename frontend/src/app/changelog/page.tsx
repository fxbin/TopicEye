'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { Flag, RefreshCw } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Button, Panel, cx } from '@/components/ui';
import { ErrorState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { productFeedbackApi, type ProductUpdateItem, type ProductUpdateKind } from '@/lib/api';
import { ReleaseNote } from './_update-timeline';
import { filterReleaseNotes } from './_release-filter';

// ── Main page ───────────────────────────────────────────────────────────

export default function ChangelogPage() {
  const { currentUser, authLoading } = useAppContext();
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState<'all' | ProductUpdateKind>('all');
  const { data, loading, error, refetch } = useFetch<ProductUpdateItem[]>(
    async () => (await productFeedbackApi.listUpdates({ status: 'shipped', limit: 300 })).items,
    [],
    { enabled: !authLoading },
  );
  const records = filterReleaseNotes(data || [], query, kind);
  const latest = filterReleaseNotes(data || [], '', 'all')[0];

  return (
    <div className="workspace-scroll">
      <div className="mx-auto max-w-[1200px] space-y-6 pb-8">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="page-title">更新记录</h1>
            <p className="mt-2 text-sm leading-7 text-ink-500">从发现线索到形成作品，看看每次更新带来的变化。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {currentUser?.role === 'admin' && <a href="/admin/updates" className="inline-flex min-h-10 items-center rounded-sm px-3 text-sm text-ink-500 hover:text-primary-text">管理更新</a>}
            <Link href="/feedback" className="inline-flex min-h-10 items-center gap-2 rounded-sm border border-ink-200 bg-white px-3 text-sm font-medium text-ink-700 hover:border-primary"><Flag size={14} />反馈建议</Link>
          </div>
        </header>

        <div className="flex flex-wrap items-center justify-between gap-3 border-y border-ink-200 py-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label="更新类别">
            {([['all', '全部更新'], ['release', '新增'], ['improvement', '改进'], ['fix', '修复']] as const).map(([value, label]) => (
              <button key={value} type="button" aria-pressed={kind === value} onClick={() => setKind(value)} className={cx('min-h-9 rounded-sm px-3 text-[13px] font-medium transition', kind === value ? 'bg-primary-light text-primary-text' : 'text-ink-500 hover:bg-ink-100')}>{label}</button>
            ))}
          </div>
          <div className="flex w-full gap-2 sm:w-auto">
            <label className="sr-only" htmlFor="release-search">搜索更新记录</label>
            <input id="release-search" value={query} onChange={event => setQuery(event.target.value)} type="search" placeholder="搜索功能、改进或日期" className="min-h-10 min-w-0 flex-1 rounded-sm border border-ink-200 bg-white px-3 text-sm sm:w-60" />
            <Button onClick={() => void refetch()} disabled={loading} aria-label="刷新更新记录"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></Button>
          </div>
        </div>
        {error && <ErrorState error={error} onRetry={() => void refetch()} panel={false} />}
        {(authLoading || loading) && !data ? <div role="status" className="space-y-4"><p className="text-sm text-ink-500">正在加载更新记录…</p><div className="admin-shimmer h-64 rounded-lg" /></div> : records.length ? (
          <div className="max-w-[1040px] space-y-6">
            {records.map(item => <ReleaseNote key={`${item.id}-${query ? 'search' : 'list'}`} item={item} latest={item.id === latest?.id} searching={Boolean(query.trim())} />)}
          </div>
        ) : !error && <Panel className="p-8 text-center"><p className="text-sm text-ink-500">{query || kind !== 'all' ? '没有匹配的更新，试试其他关键词或类别。' : '还没有已发布的更新。'}</p></Panel>}
        <p className="text-xs leading-6 text-ink-500">历史更新按产品里程碑整理，日期为归档日期。</p>
      </div>
    </div>
  );
}
