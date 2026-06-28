'use client';

import React, { useMemo, useState } from 'react';
import {
  CheckCircle2,
  CircleDot,
  ClipboardCheck,
  Clock3,
  Flag,
  Loader2,
  MessageSquareWarning,
  Plus,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Wrench,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, Toolbar, cx } from '@/components/ui';
import { ErrorState, LoadingState } from '@/components/StateView';
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
import { formatDateTime as formatTime, formatDate } from '@/lib/datetime';

type Tone = 'neutral' | 'primary' | 'teal' | 'amber' | 'purple' | 'red';

const ISSUE_STATUS_LABELS: Record<IssueFeedbackStatus, string> = {
  open: '待处理',
  triaged: '已确认',
  in_progress: '处理中',
  fixed: '已修复',
  closed: '已关闭',
};

const ISSUE_STATUS_TONES: Record<IssueFeedbackStatus, Tone> = {
  open: 'amber',
  triaged: 'primary',
  in_progress: 'purple',
  fixed: 'teal',
  closed: 'neutral',
};

const SEVERITY_LABELS: Record<IssueFeedbackSeverity, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
};

const SEVERITY_TONES: Record<IssueFeedbackSeverity, Tone> = {
  low: 'neutral',
  medium: 'primary',
  high: 'amber',
  critical: 'red',
};

const UPDATE_KIND_LABELS: Record<ProductUpdateKind, string> = {
  roadmap: '路线',
  release: '版本',
  fix: '修复',
  improvement: '优化',
};

const UPDATE_STATUS_LABELS: Record<ProductUpdateStatus, string> = {
  planned: '计划中',
  in_progress: '推进中',
  shipped: '已发布',
};

const UPDATE_STATUS_TONES: Record<ProductUpdateStatus, Tone> = {
  planned: 'neutral',
  in_progress: 'primary',
  shipped: 'teal',
};

const AREA_OPTIONS = [
  { value: 'analysis', label: 'AI 分析' },
  { value: 'trending', label: '趋势/信源' },
  { value: 'frontend', label: '界面体验' },
  { value: 'account', label: '账号/权限' },
  { value: 'general', label: '其他' },
];

function toneForBadge(tone: Tone): 'neutral' | 'primary' | 'teal' | 'amber' | 'purple' | 'red' {
  return tone;
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="mb-1 block text-xs font-bold text-gray-500">{children}</label>;
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        'h-9 w-full rounded-xs border border-gray-200 bg-white px-3 text-[13px] text-gray-800 outline-none transition placeholder:text-gray-300 focus:border-primary-border focus:ring-2 focus:ring-primary-light',
        props.className,
      )}
    />
  );
}

function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cx(
        'min-h-[104px] w-full resize-y rounded-xs border border-gray-200 bg-white px-3 py-2 text-[13px] leading-6 text-gray-800 outline-none transition placeholder:text-gray-300 focus:border-primary-border focus:ring-2 focus:ring-primary-light',
        props.className,
      )}
    />
  );
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx(
        'h-9 w-full rounded-xs border border-gray-200 bg-white px-3 text-[13px] font-bold text-gray-700 outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light',
        props.className,
      )}
    />
  );
}

function Surface({
  title,
  hint,
  icon,
  children,
  className,
}: {
  title: string;
  hint?: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Panel className={cx('p-4.5 sm:p-5', className)}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-primary-light text-primary">
            {icon}
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-black text-gray-900">{title}</div>
            {hint && <div className="mt-0.5 text-[11px] leading-5 text-gray-400">{hint}</div>}
          </div>
        </div>
      </div>
      {children}
    </Panel>
  );
}

function StatTile({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  tone: 'primary' | 'teal' | 'amber' | 'neutral';
}) {
  const classes = {
    primary: 'border-primary-border bg-primary-light text-primary',
    teal: 'border-teal-border bg-teal-light text-teal',
    amber: 'border-amber-border bg-amber-light text-amber',
    neutral: 'border-gray-200 bg-gray-50 text-gray-700',
  }[tone];
  return (
    <div className={cx('rounded-sm border p-3', classes)}>
      <div className="mb-2 flex items-center gap-2 text-[11px] font-black">
        {icon}
        {label}
      </div>
      <div className="font-mono text-2xl font-black leading-none">{value}</div>
    </div>
  );
}

function IssueStatusBadge({ status }: { status: IssueFeedbackStatus }) {
  return <Badge tone={toneForBadge(ISSUE_STATUS_TONES[status])}>{ISSUE_STATUS_LABELS[status]}</Badge>;
}

function SeverityBadge({ severity }: { severity: IssueFeedbackSeverity }) {
  return <Badge tone={toneForBadge(SEVERITY_TONES[severity])}>{SEVERITY_LABELS[severity]}</Badge>;
}

function UpdateBadge({ status }: { status: ProductUpdateStatus }) {
  return <Badge tone={toneForBadge(UPDATE_STATUS_TONES[status])}>{UPDATE_STATUS_LABELS[status]}</Badge>;
}

export default function FeedbackPage() {
  // Menu entry moved to /changelog. This page remains accessible via direct
  // URL (e.g. admin power users / deep links) with the full workbench:
  // admin view, status machine, all-issue filters, etc.
  const { currentUser, authLoading } = useAppContext();
  const isAdmin = currentUser?.role === 'admin';
  const [savingIssue, setSavingIssue] = useState(false);
  const [issueUpdatingId, setIssueUpdatingId] = useState<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [issueFilter, setIssueFilter] = useState<IssueFeedbackStatus | ''>('');

  type FeedbackPayload = {
    myIssues: IssueFeedbackItem[];
    allIssues: IssueFeedbackItem[];
    issueStats: { myOpen: number; myFixed: number; total: number; open: number; fixed: number };
    updates: ProductUpdateItem[];
  };
  const { data, loading, error: fetchError, refetch } = useFetch<FeedbackPayload>(
    async () => {
      const [mine, updateList, adminIssues] = await Promise.all([
        currentUser ? productFeedbackApi.listMine({ limit: 80 }) : Promise.resolve(null),
        productFeedbackApi.listUpdates({ limit: 160 }),
        isAdmin ? productFeedbackApi.listIssues({ status: issueFilter, limit: 200 }) : Promise.resolve(null),
      ]);
      return {
        myIssues: mine?.items || [],
        allIssues: adminIssues?.items || [],
        issueStats: {
          myOpen: mine?.open_count || 0,
          myFixed: mine?.fixed_count || 0,
          total: adminIssues?.total || 0,
          open: adminIssues?.open_count || 0,
          fixed: adminIssues?.fixed_count || 0,
        },
        updates: updateList.items || [],
      };
    },
    [currentUser, isAdmin, issueFilter],
    { enabled: !authLoading },
  );

  const myIssues = data?.myIssues ?? [];
  const allIssues = data?.allIssues ?? [];
  const issueStats = data?.issueStats ?? { myOpen: 0, myFixed: 0, total: 0, open: 0, fixed: 0 };
  const updates = data?.updates ?? [];

  const [issueForm, setIssueForm] = useState({
    title: '',
    area: 'analysis',
    severity: 'medium' as IssueFeedbackSeverity,
    description: '',
  });

  const roadmapItems = useMemo(
    () => updates.filter((item) => item.status !== 'shipped'),
    [updates],
  );
  const shippedItems = useMemo(
    () => updates.filter((item) => item.status === 'shipped'),
    [updates],
  );

  const submitIssue = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!issueForm.title.trim() || !issueForm.description.trim()) return;
    setSavingIssue(true);
    setFormError(null);
    setNotice(null);
    try {
      await productFeedbackApi.createIssue({
        title: issueForm.title.trim(),
        description: issueForm.description.trim(),
        area: issueForm.area,
        severity: issueForm.severity,
      });
      setIssueForm({ title: '', area: 'analysis', severity: 'medium', description: '' });
      setNotice('反馈已提交，后台会在处理后更新状态。');
      await refetch();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '提交反馈失败');
    } finally {
      setSavingIssue(false);
    }
  };

  const updateIssueStatus = async (issue: IssueFeedbackItem, status: IssueFeedbackStatus) => {
    setIssueUpdatingId(issue.id);
    setFormError(null);
    setNotice(null);
    try {
      await productFeedbackApi.updateIssue(issue.id, {
        status,
        resolution_note: status === 'fixed' ? issue.resolution_note || '相关问题已完成修复。' : issue.resolution_note || null,
      });
      setNotice(status === 'fixed' ? '已标记为修复。' : '反馈状态已更新。');
      await refetch();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '更新反馈状态失败');
    } finally {
      setIssueUpdatingId(null);
    }
  };

  if (authLoading || loading) {
    return <LoadingState label="正在加载反馈工作台" minHeight="60vh" />;
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page px-4 py-5 sm:px-6 lg:px-10">
      <div className="mx-auto w-full max-w-[1280px] space-y-5 pb-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge tone="primary">反馈闭环</Badge>
              {isAdmin && <Badge tone="teal">管理员视图</Badge>}
            </div>
            <h1 className="text-[26px] font-black leading-tight text-gray-900">反馈与更新</h1>
            <p className="mt-2 max-w-[760px] text-sm leading-7 text-gray-500">
              反馈可以直接提交；更新路线和记录随版本发布内置展示。
            </p>
          </div>
          <Button type="button" onClick={() => void refetch()}>
            <RefreshCw size={14} />
            刷新
          </Button>
        </div>

        {(formError || notice) && (
          <div
            className={cx(
              'rounded-sm border px-4 py-3 text-[13px] font-bold',
              formError ? 'border-red-light bg-red-light text-red' : 'border-teal-border bg-teal-light text-teal',
            )}
          >
            {formError || notice}
          </div>
        )}

        {fetchError && (
          <div className="mb-4">
            <ErrorState error={fetchError} onRetry={() => void refetch()} panel={false} />
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {currentUser ? (
            <>
              <StatTile label="我的待处理" value={issueStats.myOpen} icon={<CircleDot size={14} />} tone="amber" />
              <StatTile label="我的已修复" value={issueStats.myFixed} icon={<CheckCircle2 size={14} />} tone="teal" />
            </>
          ) : (
            <>
              <StatTile label="反馈提交" value="匿名" icon={<CircleDot size={14} />} tone="amber" />
              <StatTile label="状态跟踪" value="登录" icon={<CheckCircle2 size={14} />} tone="teal" />
            </>
          )}
          <StatTile label="路线推进" value={roadmapItems.length} icon={<Flag size={14} />} tone="primary" />
          <StatTile label="更新记录" value={shippedItems.length} icon={<Rocket size={14} />} tone="neutral" />
        </div>

        <div className={cx('grid gap-5', currentUser ? 'xl:grid-cols-[420px_1fr]' : 'max-w-[520px]')}>
          <Surface title="提交问题反馈" hint="问题越具体，越容易定位和修复" icon={<MessageSquareWarning size={16} />}>
            <form className="space-y-3" onSubmit={submitIssue}>
              <div>
                <FieldLabel>标题</FieldLabel>
                <TextInput
                  value={issueForm.title}
                  onChange={(event) => setIssueForm((prev) => ({ ...prev, title: event.target.value }))}
                  placeholder="例如：新进来的选题一直 pending"
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <FieldLabel>模块</FieldLabel>
                  <Select
                    value={issueForm.area}
                    onChange={(event) => setIssueForm((prev) => ({ ...prev, area: event.target.value }))}
                  >
                    {AREA_OPTIONS.map((area) => (
                      <option key={area.value} value={area.value}>{area.label}</option>
                    ))}
                  </Select>
                </div>
                <div>
                  <FieldLabel>影响程度</FieldLabel>
                  <Select
                    value={issueForm.severity}
                    onChange={(event) => setIssueForm((prev) => ({ ...prev, severity: event.target.value as IssueFeedbackSeverity }))}
                  >
                    <option value="low">低</option>
                    <option value="medium">中</option>
                    <option value="high">高</option>
                    <option value="critical">严重</option>
                  </Select>
                </div>
              </div>
              <div>
                <FieldLabel>问题描述</FieldLabel>
                <TextArea
                  value={issueForm.description}
                  onChange={(event) => setIssueForm((prev) => ({ ...prev, description: event.target.value }))}
                  placeholder="描述复现路径、预期结果、实际结果，或者你看到的异常状态。"
                />
              </div>
              <Button
                type="submit"
                variant="primary"
                disabled={savingIssue || !issueForm.title.trim() || !issueForm.description.trim()}
                className="w-full"
              >
                {savingIssue ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                提交反馈
              </Button>
            </form>
          </Surface>

          {currentUser && (
            <Surface title="我的反馈" hint="修复状态会在这里回流" icon={<ClipboardCheck size={16} />}>
              <div className="space-y-3">
                {myIssues.length === 0 ? (
                  <div className="rounded-sm border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm font-bold text-gray-400">
                    还没有提交过反馈
                  </div>
                ) : myIssues.map((issue) => (
                  <IssueRow key={issue.id} issue={issue} compact />
                ))}
              </div>
            </Surface>
          )}
        </div>

        {isAdmin && (
          <div className="grid gap-5">
            <Surface title="全部反馈处理" hint={`${issueStats.open} 个待处理，${issueStats.fixed} 个已修复`} icon={<ShieldCheck size={16} />}>
              <Toolbar className="mb-3 justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    value={issueFilter}
                    onChange={(event) => setIssueFilter(event.target.value as IssueFeedbackStatus | '')}
                    className="w-[150px]"
                  >
                    <option value="">全部状态</option>
                    <option value="open">待处理</option>
                    <option value="triaged">已确认</option>
                    <option value="in_progress">处理中</option>
                    <option value="fixed">已修复</option>
                    <option value="closed">已关闭</option>
                  </Select>
                  <Badge tone="neutral">共 {issueStats.total} 条</Badge>
                </div>
              </Toolbar>
              <div className="space-y-3">
                {allIssues.length === 0 ? (
                  <div className="rounded-sm border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm font-bold text-gray-400">
                    当前筛选下没有反馈
                  </div>
                ) : allIssues.map((issue) => (
                  <div key={issue.id} className="rounded-sm border border-gray-200 bg-white p-3.5">
                    <IssueRow issue={issue} />
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-gray-100 pt-3">
                      <div className="text-[11px] font-bold text-gray-400">
                        提交人：{issue.reporter_name || issue.reporter_email || (issue.user_id ? `用户 ${issue.user_id}` : '匿名用户')}
                      </div>
                      <Toolbar>
                        <Button
                          type="button"
                          onClick={() => updateIssueStatus(issue, 'triaged')}
                          disabled={issueUpdatingId === issue.id || issue.status === 'triaged'}
                        >
                          <CircleDot size={13} />
                          确认
                        </Button>
                        <Button
                          type="button"
                          onClick={() => updateIssueStatus(issue, 'in_progress')}
                          disabled={issueUpdatingId === issue.id || issue.status === 'in_progress'}
                        >
                          <Wrench size={13} />
                          处理中
                        </Button>
                        <Button
                          type="button"
                          variant="success"
                          onClick={() => updateIssueStatus(issue, 'fixed')}
                          disabled={issueUpdatingId === issue.id || issue.status === 'fixed'}
                        >
                          {issueUpdatingId === issue.id ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
                          已修复
                        </Button>
                      </Toolbar>
                    </div>
                  </div>
                ))}
              </div>
            </Surface>
          </div>
        )}

        <div className="grid gap-5 xl:grid-cols-2">
          <Surface title="更新路线" hint="计划中和推进中的事项" icon={<Flag size={16} />}>
            <UpdateList
              items={roadmapItems}
              emptyText="暂无路线图事项"
            />
          </Surface>
          <Surface title="更新记录" hint="已发布版本、修复和优化" icon={<Rocket size={16} />}>
            <UpdateList
              items={shippedItems}
              emptyText="暂无更新记录"
            />
          </Surface>
        </div>
      </div>
    </div>
  );
}

function IssueRow({ issue, compact = false }: { issue: IssueFeedbackItem; compact?: boolean }) {
  return (
    <div className={cx('rounded-sm border border-gray-200 bg-white', compact ? 'p-3.5' : 'border-0 p-0')}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <IssueStatusBadge status={issue.status} />
        <SeverityBadge severity={issue.severity} />
        <Badge tone="neutral">{AREA_OPTIONS.find((area) => area.value === issue.area)?.label || issue.area}</Badge>
        <span className="text-[11px] font-bold text-gray-400">{formatTime(issue.created_at)}</span>
      </div>
      <div className="text-sm font-black leading-6 text-gray-900">{issue.title}</div>
      <p className="mt-1 text-[13px] leading-6 text-gray-500">{issue.description}</p>
      {issue.resolution_note && (
        <div className="mt-2 rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold leading-5 text-teal">
          {issue.resolution_note}
        </div>
      )}
      {issue.fixed_at && (
        <div className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-bold text-teal">
          <CheckCircle2 size={13} />
          {formatTime(issue.fixed_at)} 修复
        </div>
      )}
    </div>
  );
}

function UpdateList({
  items,
  emptyText,
}: {
  items: ProductUpdateItem[];
  emptyText: string;
}) {
  if (items.length === 0) {
    return (
      <div className="rounded-sm border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm font-bold text-gray-400">
        {emptyText}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((version) => (
        <div key={version.id} className="rounded-sm border border-gray-200 bg-white p-3.5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <UpdateBadge status={version.status} />
            <Badge tone="purple">{version.version}</Badge>
            <span className="text-[11px] font-bold text-gray-500">
              {version.items.length} 项更新
            </span>
            <span className="inline-flex items-center gap-1 text-[11px] font-bold text-gray-400">
              <Clock3 size={12} />
              {version.status === 'shipped' ? formatTime(version.shipped_at) : formatDate(version.target_date)}
            </span>
          </div>
          <ul className="space-y-2.5">
            {version.items.map((entry, idx) => (
              <li key={idx} className="border-l-2 border-gray-100 pl-3">
                <div className="mb-1 flex items-center gap-2">
                  <Badge tone={entry.kind === 'fix' ? 'amber' : entry.kind === 'release' ? 'primary' : entry.kind === 'improvement' ? 'teal' : 'neutral'}>
                    {UPDATE_KIND_LABELS[entry.kind]}
                  </Badge>
                  <span className="text-sm font-black leading-6 text-gray-900">{entry.title}</span>
                </div>
                <p className="text-[13px] leading-6 text-gray-500">{entry.description}</p>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
