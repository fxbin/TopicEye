'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  CircleDot,
  Flag,
  Loader2,
  RefreshCw,
  X,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { ErrorState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { useDialogFocus } from '@/components/useDialogFocus';
import {
  productFeedbackApi,
  type IssueFeedbackItem,
  type IssueFeedbackSeverity,
  type ProductUpdateItem,
  type ProductUpdateKind,
} from '@/lib/api';
import { ReleaseNote } from './_update-timeline';
import { filterReleaseNotes } from './_release-filter';
import { timeAgoShort as formatRelative } from '@/lib/datetime';
import {
  ISSUE_STATUS_LABELS,
  ISSUE_STATUS_TONES,
  SEVERITY_LABELS,
  SEVERITY_TONES,
} from '@/lib/product-feedback-labels';

// 注：Tone 类型与 product-feedback 标签映射已收敛到公共模块：
// - Tone ← @/components/ui
// - 标签映射 ← @/lib/product-feedback-labels（修复 R9 值冲突）

// ── Feedback panel (简化版：写表单 + 最近 10 条历史) ───────────────────

function FeedbackPanel({ onClose, onSubmitted }: { onClose: () => void; onSubmitted: () => void }) {
  const { dialogRef, onKeyDown } = useDialogFocus<HTMLDivElement>(true, onClose);
  const { currentUser } = useAppContext();
  const [myIssues, setMyIssues] = useState<IssueFeedbackItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({
    title: '',
    description: '',
    severity: 'medium' as IssueFeedbackSeverity,
  });

  const loadMyIssues = useCallback(async () => {
    if (!currentUser) {
      setMyIssues([]);
      return;
    }
    try {
      const resp = await productFeedbackApi.listMine({ limit: 10 });
      setMyIssues(resp.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [currentUser]);

  useEffect(() => {
    loadMyIssues();
  }, [loadMyIssues]);

  const handleSubmit = async () => {
    if (!form.title.trim() || !form.description.trim()) {
      setError('请填写标题和描述');
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await productFeedbackApi.createIssue({
        title: form.title.trim(),
        description: form.description.trim(),
        severity: form.severity,
      });
      setNotice('反馈已提交，我们会尽快处理');
      setForm({ title: '', description: '', severity: 'medium' });
      await loadMyIssues();
      onSubmitted();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div aria-hidden="true" className="fixed inset-0 z-50 bg-black/40" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-panel-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="pointer-events-none fixed inset-0 z-[51] flex items-center justify-center p-4 sm:p-6"
      >
      <div className="pointer-events-auto flex h-full max-h-[90vh] w-full max-w-3xl flex-col rounded-md bg-white shadow-xl">
        {/* Header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-200 px-5 py-3.5">
          <div>
            <h2 id="feedback-panel-title" className="flex items-center gap-2 text-base font-semibold text-gray-900">
              <Flag size={16} className="text-orange" />
              提交反馈
            </h2>
            <p className="mt-0.5 text-[12px] text-gray-500">
              提交后我们会在站内通知你处理进度
            </p>
          </div>
          <Button type="button" variant="ghost" onClick={onClose} className="!px-2 !py-1" aria-label="关闭反馈面板">
            <X size={16} />
          </Button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {(error || notice) && (
            <div
              className={cx(
                'mb-3 rounded-sm border px-3 py-2 text-[13px]',
                error
                  ? 'border-red-light bg-red-light/30 text-red'
                  : 'border-teal-border bg-teal-light/30 text-teal',
              )}
            >
              {error || notice}
            </div>
          )}

          {/* Form */}
          <div className="mb-5 space-y-3 rounded-sm border border-gray-200 bg-gray-50/50 p-3.5">
            <div>
              <label className="mb-1 block text-[12px] font-medium text-gray-700">标题</label>
              <input
                type="text"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="一句话描述问题或建议"
                maxLength={100}
                className="w-full rounded-sm border border-gray-200 bg-white px-3 py-1.5 text-[13px] focus:border-orange focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-gray-700">详细描述</label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="复现步骤、期望行为、实际行为等"
                rows={4}
                maxLength={2000}
                className="w-full rounded-sm border border-gray-200 bg-white px-3 py-1.5 text-[13px] focus:border-orange focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-gray-700">严重程度</label>
              <div className="flex gap-1.5">
                {(['low', 'medium', 'high'] as const).map((sev) => (
                  <button
                    key={sev}
                    type="button"
                    onClick={() => setForm({ ...form, severity: sev })}
                    className={cx(
                      'rounded-sm border px-3 py-1 text-[12px] transition',
                      form.severity === sev
                        ? 'border-orange bg-orange text-white'
                        : 'border-gray-200 bg-white text-gray-700 hover:border-orange/50',
                    )}
                  >
                    {SEVERITY_LABELS[sev]}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex justify-end">
              <Button type="button" onClick={handleSubmit} disabled={saving || !currentUser}>
                {saving && <Loader2 size={14} className="animate-spin" />}
                提交反馈
              </Button>
            </div>
            {!currentUser && (
              <p className="text-[12px] text-amber">请先登录后提交反馈</p>
            )}
          </div>

          {/* My feedback history */}
          <div>
            <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-gray-900">
              <CircleDot size={14} className="text-gray-500" />
              我的反馈历史
            </h3>
            {myIssues.length === 0 ? (
              <p className="rounded-sm bg-gray-50 px-3 py-4 text-center text-[12px] text-gray-500">
                {currentUser ? '暂无反馈记录' : '登录后查看历史'}
              </p>
            ) : (
              <ul className="space-y-2">
                {myIssues.map((issue) => (
                  <li
                    key={issue.id}
                    className="rounded-sm border border-gray-100 bg-white px-3 py-2.5"
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <Badge tone={ISSUE_STATUS_TONES[issue.status]}>
                        {ISSUE_STATUS_LABELS[issue.status]}
                      </Badge>
                      <Badge tone={SEVERITY_TONES[issue.severity]}>
                        严重度 {SEVERITY_LABELS[issue.severity]}
                      </Badge>
                      <span className="ml-auto text-[11px] text-gray-500">
                        {formatRelative(issue.updated_at || issue.created_at)}
                      </span>
                    </div>
                    <p className="text-[13px] font-semibold text-gray-900">{issue.title}</p>
                    {issue.resolution_note && (
                      <div className="mt-1.5 rounded-sm border-l-2 border-orange/50 bg-orange/5 px-2.5 py-1.5 text-[12px] text-gray-700">
                        <span className="font-semibold text-orange">处理记录：</span>
                        {issue.resolution_note}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-[11px] text-gray-500">
              显示最近 10 条。需要查看完整历史请到{' '}
              <a href="/admin/feedback" className="text-orange hover:underline">反馈工作台</a>。
            </p>
          </div>
        </div>
      </div>
      </div>
    </>
  );
}

// ── Main page ───────────────────────────────────────────────────────────

export default function ChangelogPage() {
  const { currentUser, authLoading } = useAppContext();
  const [showFeedback, setShowFeedback] = useState(false);
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
            <Button onClick={() => setShowFeedback(true)}><Flag size={14} />反馈建议</Button>
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
      {showFeedback && <FeedbackPanel onClose={() => setShowFeedback(false)} onSubmitted={() => setShowFeedback(false)} />}
    </div>
  );
}
