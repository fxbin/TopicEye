'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { Flag, Loader2, RefreshCw } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel } from '@/components/ui';
import { ErrorState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { productFeedbackApi } from '@/lib/api';
import type { IssueFeedbackListResponse, IssueFeedbackSeverity } from '@/types/product-feedback';
import { ISSUE_STATUS_LABELS, ISSUE_STATUS_TONES, SEVERITY_LABELS } from '@/lib/product-feedback-labels';
import { timeAgoShort } from '@/lib/datetime';

const PAGE_SIZE = 10;

export default function FeedbackPage() {
  const { currentUser, authLoading } = useAppContext();
  return (
    <div className="workspace-scroll">
      <div className="mx-auto max-w-[1040px] space-y-6 pb-8">
        <header>
          <h1 className="page-title">反馈建议</h1>
          <p className="mt-2 text-sm leading-7 text-ink-500">告诉我们遇到的问题或希望改进的地方，在这里查看自己的反馈和处理回复。</p>
        </header>
        {authLoading ? <p role="status">正在检查登录状态…</p> : currentUser ? (
          <FeedbackWorkspace key={currentUser.id} />
        ) : <Panel className="p-6"><Link href="/login?returnTo=%2Ffeedback" className="text-primary-text underline">登录后提交和查看反馈</Link></Panel>}
      </div>
    </div>
  );
}

export function FeedbackWorkspace() {
  const [form, setForm] = useState({ title: '', description: '', severity: 'medium' as IssueFeedbackSeverity });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const { data, loading, error: historyError, refetch } = useFetch<IssueFeedbackListResponse>(
    () => productFeedbackApi.listMine({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }),
    [page, revision],
  );

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    if (form.title.trim().length < 2 || form.description.trim().length < 5) {
      setError('标题至少 2 个字，详细描述至少 5 个字');
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await productFeedbackApi.createIssue({ ...form, title: form.title.trim(), description: form.description.trim() });
      setForm({ title: '', description: '', severity: 'medium' });
      setNotice('反馈已提交，可以在下方查看处理进度');
      setPage(1);
      setRevision(value => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败，请重试');
    } finally {
      setSaving(false);
    }
  }

  return <>
    <Panel className="p-5 sm:p-6">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold"><Flag size={17} />提交反馈</h2>
      <form onSubmit={submit} className="space-y-4">
        {error && <p role="alert" className="rounded-sm bg-red-light p-3 text-sm text-red">{error}</p>}
        {notice && <p role="status" className="rounded-sm bg-teal-light p-3 text-sm text-teal">{notice}</p>}
        <div>
          <label htmlFor="feedback-title" className="mb-1 block text-sm font-medium">标题</label>
          <input id="feedback-title" required minLength={2} maxLength={200} disabled={saving} value={form.title} onChange={event => setForm({ ...form, title: event.target.value })} placeholder="一句话描述问题或建议" className="min-h-11 w-full rounded-sm border border-ink-200 px-3 text-sm" />
        </div>
        <div>
          <label htmlFor="feedback-description" className="mb-1 block text-sm font-medium">详细描述</label>
          <textarea id="feedback-description" required minLength={5} maxLength={5000} rows={5} disabled={saving} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} placeholder="遇到了什么、如何复现，或者希望怎样改进" className="w-full rounded-sm border border-ink-200 px-3 py-2 text-sm" />
        </div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <label htmlFor="feedback-severity" className="mb-1 block text-sm font-medium">影响程度</label>
            <select id="feedback-severity" disabled={saving} value={form.severity} onChange={event => setForm({ ...form, severity: event.target.value as IssueFeedbackSeverity })} className="min-h-11 rounded-sm border border-ink-200 px-3 text-sm">
              {(['low', 'medium', 'high'] as const).map(value => <option key={value} value={value}>{SEVERITY_LABELS[value]}</option>)}
            </select>
          </div>
          <Button type="submit" disabled={saving}>{saving && <Loader2 size={14} className="animate-spin" />}{saving ? '正在提交…' : '提交反馈'}</Button>
        </div>
      </form>
    </Panel>
    <section aria-labelledby="my-feedback-title" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="my-feedback-title" className="text-base font-semibold">我的反馈{data ? `（${data.total}）` : ''}</h2>
        <Button onClick={() => void refetch()} disabled={loading} aria-label="刷新我的反馈"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />刷新</Button>
      </div>
      {historyError && <ErrorState error={historyError} onRetry={() => void refetch()} panel={false} />}
      {loading ? <p role="status" className="text-sm text-ink-500">正在加载我的反馈…</p> : !historyError && (data?.items.length ? (
        <ul className="space-y-3">
          {data.items.map(issue => <li key={issue.id}><Panel className="space-y-3 p-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={ISSUE_STATUS_TONES[issue.status]}>{ISSUE_STATUS_LABELS[issue.status]}</Badge>
              <span className="text-xs text-ink-500">{timeAgoShort(issue.updated_at || issue.created_at)}</span>
            </div>
            <h3 className="break-words font-semibold">{issue.title}</h3>
            <p className="whitespace-pre-wrap break-words text-sm leading-6 text-ink-500">{issue.description}</p>
            {issue.resolution_note && <div className="rounded-sm border-l-2 border-primary bg-primary-light p-3 text-sm leading-6"><span className="font-semibold">处理回复：</span><span className="whitespace-pre-wrap break-words">{issue.resolution_note}</span></div>}
          </Panel></li>)}
        </ul>
      ) : <Panel className="p-6 text-sm text-ink-500">还没有反馈记录，提交后会显示在这里。</Panel>)}
      {data && data.total > PAGE_SIZE && <nav aria-label="我的反馈分页" className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <Button disabled={loading || page <= 1} onClick={() => setPage(value => value - 1)}>上一页</Button>
        <span>第 {page} / {Math.ceil(data.total / PAGE_SIZE)} 页</span>
        <Button disabled={loading || page * PAGE_SIZE >= data.total} onClick={() => setPage(value => value + 1)}>下一页</Button>
      </nav>}
    </section>
  </>;
}
