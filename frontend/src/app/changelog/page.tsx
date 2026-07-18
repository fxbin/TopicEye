'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  ChevronDown,
  CircleDot,
  Flag,
  Loader2,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Wrench,
  X,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx, type Tone } from '@/components/ui';
import { ErrorState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import {
  productFeedbackApi,
  type IssueFeedbackItem,
  type IssueFeedbackSeverity,
  type IssueFeedbackStatus,
  type ProductUpdateItem,
  type ProductUpdateKind,
  type ProductUpdateStatus,
} from '@/lib/api';
import { timeAgoShort as formatRelative } from '@/lib/datetime';
import {
  ISSUE_STATUS_LABELS,
  ISSUE_STATUS_TONES,
  SEVERITY_LABELS,
  SEVERITY_TONES,
  UPDATE_KIND_LABELS,
  UPDATE_KIND_TONES,
  UPDATE_STATUS_LABELS,
  UPDATE_STATUS_TONES,
} from '@/lib/product-feedback-labels';

// 注：Tone 类型与 product-feedback 标签映射已收敛到公共模块：
// - Tone ← @/components/ui
// - 标签映射 ← @/lib/product-feedback-labels（修复 R9 值冲突）

// ── Helpers (display formatters) ────────────────────────────────────────

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// ── Update timeline (发版记录) ──────────────────────────────────────────

function UpdateItemCard({ entry, itemUpdatedAt }: { entry: ProductUpdateItem['items'][number]; itemUpdatedAt: string }) {
  return (
    <div className="rounded-sm border border-gray-100 bg-white px-3 py-2.5">
      <div className="mb-1 flex items-center gap-2">
        <Badge tone={UPDATE_KIND_TONES[entry.kind]}>{UPDATE_KIND_LABELS[entry.kind]}</Badge>
        <span className="text-[12px] text-gray-500">{formatRelative(itemUpdatedAt)}</span>
      </div>
      <p className="text-[13px] leading-6 text-gray-700">{entry.description}</p>
    </div>
  );
}

function UpdateCard({ item }: { item: ProductUpdateItem }) {
  const isShipped = item.status === 'shipped';
  // shipped 默认展开（用户最关心的历史变更），其他状态默认折叠
  const [expanded, setExpanded] = useState(isShipped);

  // 折叠状态摘要：按 kind 统计
  const kindCounts = item.items.reduce<Record<string, number>>((acc, it) => {
    acc[it.kind] = (acc[it.kind] || 0) + 1;
    return acc;
  }, {});

  return (
    <Panel className="p-4.5 sm:p-5">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="mb-3 flex w-full flex-wrap items-center justify-between gap-2 border-b border-gray-100 pb-3 text-left"
      >
        <div className="flex items-center gap-2">
          <div
            className={cx(
              'flex h-9 w-9 items-center justify-center rounded-sm',
              isShipped ? 'bg-teal-light text-teal' : 'bg-amber-light text-amber',
            )}
          >
            {isShipped ? <Rocket size={16} /> : <Wrench size={16} />}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[15px] font-black text-gray-900">{item.version}</span>
              <Badge tone={UPDATE_STATUS_TONES[item.status]}>{UPDATE_STATUS_LABELS[item.status]}</Badge>
            </div>
            <p className="text-[12px] text-gray-500">
              {isShipped && item.shipped_at ? `发布于 ${formatDate(item.shipped_at)}` :
                item.target_date ? `计划 ${formatDate(item.target_date)}` : '近期规划'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[12px] text-gray-500">
          {!expanded && item.items.length > 0 && (
            <span className="hidden gap-1 sm:flex">
              {Object.entries(kindCounts).map(([k, n]) => (
                <Badge key={k} tone={UPDATE_KIND_TONES[k as ProductUpdateKind]}>
                  {UPDATE_KIND_LABELS[k as ProductUpdateKind]} {n}
                </Badge>
              ))}
            </span>
          )}
          <span>{item.items.length} 项</span>
          <ChevronDown
            size={16}
            className={cx(
              'transition-transform',
              expanded && 'rotate-180',
            )}
          />
        </div>
      </button>
      {expanded && (
        <div className="space-y-2">
          {item.items.length === 0 ? (
            <p className="py-3 text-center text-[13px] text-gray-500">该版本暂无更新项</p>
          ) : (
            item.items.map((entry, idx) => (
              <UpdateItemCard key={`${item.id}-${idx}`} entry={entry} itemUpdatedAt={item.updated_at} />
            ))
          )}
        </div>
      )}
    </Panel>
  );
}

// ── Feedback panel (简化版：写表单 + 最近 10 条历史) ───────────────────

function FeedbackPanel({ onClose, onSubmitted }: { onClose: () => void; onSubmitted: () => void }) {
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 sm:p-6">
      <div className="flex h-full max-h-[90vh] w-full max-w-3xl flex-col rounded-md bg-white shadow-xl">
        {/* Header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-200 px-5 py-3.5">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold text-gray-900">
              <Flag size={16} className="text-orange" />
              提交反馈
            </h2>
            <p className="mt-0.5 text-[12px] text-gray-500">
              提交后我们会在站内通知你处理进度
            </p>
          </div>
          <Button type="button" variant="ghost" onClick={onClose} className="!px-2 !py-1">
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
              <a href="/feedback" className="text-orange hover:underline">反馈工作台</a>。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────────

export default function ChangelogPage() {
  const { currentUser, authLoading } = useAppContext();
  const [showFeedback, setShowFeedback] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | ProductUpdateStatus>('all');
  const [versionQuery, setVersionQuery] = useState('');

  const { data: updates, loading, error, refetch } = useFetch<ProductUpdateItem[]>(
    async () => {
      const resp = await productFeedbackApi.listUpdates({ limit: 50 });
      return resp.items;
    },
    [],
    { enabled: !authLoading },
  );

  const filteredUpdates = (updates || [])
    .filter((u) => statusFilter === 'all' || u.status === statusFilter)
    .filter((u) => !versionQuery.trim() || u.version.toLowerCase().includes(versionQuery.trim().toLowerCase()));

  if (authLoading || loading) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page">
        <div className="inline-flex items-center gap-2 text-sm font-bold text-gray-500">
          <Loader2 size={16} className="animate-spin" />
          正在加载更新记录
        </div>
      </div>
    );
  }

  const shippedCount = (updates || []).filter((u) => u.status === 'shipped').length;
  const inProgressCount = (updates || []).filter((u) => u.status === 'in_progress').length;

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page px-4 py-5 sm:px-6 lg:px-10">
      <div className="mx-auto w-full max-w-[960px] space-y-5 pb-8">
        {/* Header */}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge tone="primary">产品更新</Badge>
              {shippedCount > 0 && <Badge tone="teal">已发布 {shippedCount}</Badge>}
              {inProgressCount > 0 && <Badge tone="amber">进行中 {inProgressCount}</Badge>}
            </div>
            <h1 className="text-[26px] font-black leading-tight text-gray-900">更新记录</h1>
            <p className="mt-2 max-w-[760px] text-sm leading-7 text-gray-500">
              查看 TopicEye 的最新发版、新增能力和修复。有想法或遇到问题？随时给我们反馈。
            </p>
          </div>
          <div className="flex gap-2">
            {currentUser ? (
              <Button type="button" onClick={() => setShowFeedback(true)}>
                <Flag size={14} />
                反馈
              </Button>
            ) : (
              <Button
                type="button"
                variant="secondary"
                onClick={() => window.location.href = '/login'}
                title="请先登录后提交反馈"
              >
                <Flag size={14} />
                登录后反馈
              </Button>
            )}
            <Button type="button" variant="secondary" onClick={() => void refetch()}>
              <RefreshCw size={14} />
              刷新
            </Button>
          </div>
        </div>

        {error && (
          <div className="mb-4">
            <ErrorState error={error} onRetry={() => void refetch()} panel={false} />
          </div>
        )}

        {/* Status filter tabs + version search */}
        {(updates || []).length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={versionQuery}
              onChange={(e) => setVersionQuery(e.target.value)}
              placeholder="按版本号搜索（如 v0.2、v1.0）"
              className="flex-1 min-w-[200px] rounded-sm border border-gray-200 bg-white px-3 py-1 text-[12px] focus:border-orange focus:outline-none"
            />
            {([
              { value: 'all', label: '全部', count: (updates || []).length },
              { value: 'shipped', label: '已发布', count: (updates || []).filter((u) => u.status === 'shipped').length },
              { value: 'in_progress', label: '进行中', count: (updates || []).filter((u) => u.status === 'in_progress').length },
              { value: 'planned', label: '已规划', count: (updates || []).filter((u) => u.status === 'planned').length },
            ] as const).map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => setStatusFilter(tab.value as 'all' | ProductUpdateStatus)}
                className={cx(
                  'flex items-center gap-1.5 rounded-sm border px-3 py-1 text-[12px] transition',
                  statusFilter === tab.value
                    ? 'border-orange bg-orange text-white'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-orange/50',
                )}
              >
                {tab.label}
                <span className={cx(
                  'rounded-full px-1.5 text-[10px]',
                  statusFilter === tab.value ? 'bg-white/20' : 'bg-gray-100',
                )}>
                  {tab.count}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Timeline */}
        {filteredUpdates.length === 0 ? (
          <Panel className="p-8 text-center">
            <ShieldCheck className="mx-auto mb-3 h-10 w-10 text-gray-300" />
            <p className="text-[14px] text-gray-500">
              {versionQuery.trim()
                ? `没有匹配「${versionQuery}」的发版记录`
                : statusFilter === 'all'
                  ? '暂无更新记录'
                  : `暂无「${statusFilter}」状态的发版记录`}
            </p>
          </Panel>
        ) : (
          <div className="space-y-3">
            {filteredUpdates.map((item) => (
              <UpdateCard key={item.id} item={item} />
            ))}
          </div>
        )}

        <p className="pt-2 text-center text-[12px] text-gray-500">
          反馈对话框只展示最近 10 条 ·{' '}
          <a href="/feedback" className="text-orange hover:underline">
            完整反馈工作台（管理员视图、状态机等）&rarr;
          </a>
        </p>
      </div>

      {showFeedback && (
        <FeedbackPanel
          onClose={() => setShowFeedback(false)}
          onSubmitted={() => void refetch()}
        />
      )}
    </div>
  );
}
