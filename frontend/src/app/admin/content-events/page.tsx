'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  GitMerge,
  Play,
  RefreshCw,
  ShieldAlert,
  X,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import {
  AdminModal,
  AdminModalFooter,
  AdminNoticeBanner,
  AdminPageHeader,
  AdminPageShell,
} from '@/components/admin-ui';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { LoadingState } from '@/components/StateView';
import { formatDateTime } from '@/lib/datetime';
import { contentEventsAdminApi } from '@/lib/api';
import type {
  ContentEventNormalizationMode,
  ContentEventNormalizationScope,
  ContentEventNormalizeResponse,
  ContentEventRelation,
  ContentEventReviewItem,
  ContentEventReviewStatus,
} from '@/lib/api';

const PAGE_SIZE = 20;

const REVIEW_TABS: Array<{
  value: ContentEventReviewStatus;
  label: string;
}> = [
  { value: 'pending', label: '待审核' },
  { value: 'auto', label: '自动通过' },
  { value: 'confirmed', label: '人工确认' },
  { value: 'rejected', label: '已拒绝' },
];

const RELATION_OPTIONS: Array<{
  value: ContentEventRelation;
  label: string;
}> = [
  { value: 'duplicate', label: '重复消息' },
  { value: 'corroboration', label: '交叉佐证' },
  { value: 'update', label: '后续进展' },
];

const REVIEW_STATUS_META: Record<
  ContentEventReviewStatus,
  { label: string; tone: 'amber' | 'teal' | 'primary' | 'red' }
> = {
  pending: { label: '待审核', tone: 'amber' },
  auto: { label: '自动通过', tone: 'primary' },
  confirmed: { label: '人工确认', tone: 'teal' },
  rejected: { label: '已拒绝', tone: 'red' },
};

const RELATION_LABELS: Record<ContentEventRelation, string> = {
  duplicate: '重复消息',
  corroboration: '交叉佐证',
  update: '后续进展',
};

interface ReviewDraft {
  relation: ContentEventRelation;
  reason: string;
}

type ApiError = Error & { status?: number };

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function resultSummary(response: ContentEventNormalizeResponse): string {
  const entries = Object.entries(response.result)
    .filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value))
    .slice(0, 6)
    .map(([key, value]) => `${key}: ${String(value)}`);
  return entries.length > 0 ? entries.join('，') : '任务已受理';
}

export default function ContentEventsAdminPage() {
  const { currentUser, authLoading } = useAppContext();
  const [reviewStatus, setReviewStatus] =
    useState<ContentEventReviewStatus>('pending');
  const [reviews, setReviews] = useState<ContentEventReviewItem[]>([]);
  const [drafts, setDrafts] = useState<Record<number, ReviewDraft>>({});
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [rowBusyId, setRowBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const requestSequence = useRef(0);

  const [hours, setHours] = useState(24);
  const [scope, setScope] =
    useState<ContentEventNormalizationScope>('public');
  const [ownerUserId, setOwnerUserId] = useState('');
  const [mode, setMode] = useState<ContentEventNormalizationMode>('shadow');
  const [normalizing, setNormalizing] = useState(false);
  const [normalizationError, setNormalizationError] = useState<string | null>(
    null,
  );
  const [normalizationNotice, setNormalizationNotice] = useState<string | null>(
    null,
  );
  const [showWriteConfirmation, setShowWriteConfirmation] = useState(false);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const pageEnd = Math.min(page * PAGE_SIZE, total);

  const loadReviews = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    try {
      const response = await contentEventsAdminApi.listReviews({
        page,
        page_size: PAGE_SIZE,
        review_status: reviewStatus,
      });
      if (sequence !== requestSequence.current) return;
      setReviews(response.items);
      setTotal(response.total);
      setDrafts(
        Object.fromEntries(
          response.items.map((item) => [
            item.id,
            { relation: item.relation_type, reason: '' },
          ]),
        ),
      );
    } catch (requestError) {
      if (sequence !== requestSequence.current) return;
      setError(errorMessage(requestError, '审核队列加载失败'));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [page, reviewStatus]);

  useEffect(() => {
    if (!authLoading && currentUser?.role === 'admin') {
      void loadReviews();
    }
  }, [authLoading, currentUser, loadReviews]);

  const patchDraft = (
    memberId: number,
    patch: Partial<ReviewDraft>,
  ): void => {
    setDrafts((current) => ({
      ...current,
      [memberId]: {
        relation: current[memberId]?.relation ?? 'duplicate',
        reason: current[memberId]?.reason ?? '',
        ...patch,
      },
    }));
  };

  const reviewMember = async (
    item: ContentEventReviewItem,
    decision: 'accept' | 'reject',
  ): Promise<void> => {
    const draft = drafts[item.id];
    const reason = draft?.reason.trim() ?? '';
    if (!reason) {
      setError('请先填写审核理由。');
      return;
    }

    setRowBusyId(item.id);
    setError(null);
    setNotice(null);
    try {
      await contentEventsAdminApi.reviewMember(item.id, {
        decision,
        ...(decision === 'accept'
          ? { relation_type: draft?.relation ?? item.relation_type }
          : {}),
        reason,
        expected_version: item.event_version,
      });
      setNotice(
        decision === 'accept'
          ? `已确认「${item.title}」的事件关系。`
          : `已拒绝「${item.title}」的事件关系。`,
      );
      if (reviews.length === 1 && page > 1) {
        setPage((current) => current - 1);
      } else {
        await loadReviews();
      }
    } catch (requestError) {
      const apiError = requestError as ApiError;
      if (apiError.status === 409) {
        setError('事件版本已被其他任务或管理员更新，请刷新队列后重新审核。');
      } else {
        setError(errorMessage(requestError, '审核操作失败'));
      }
    } finally {
      setRowBusyId(null);
    }
  };

  const normalizationPayload = useMemo(() => {
    const ownerId = Number(ownerUserId);
    return {
      hours,
      mode,
      scope,
      ...(scope === 'user' && Number.isInteger(ownerId) && ownerId > 0
        ? { owner_user_id: ownerId }
        : {}),
    };
  }, [hours, mode, ownerUserId, scope]);

  const validateNormalization = (): string | null => {
    if (!Number.isInteger(hours) || hours < 1 || hours > 720) {
      return '归一化窗口必须是 1–720 小时之间的整数。';
    }
    if (
      scope === 'user' &&
      (!Number.isInteger(Number(ownerUserId)) || Number(ownerUserId) < 1)
    ) {
      return '用户范围归一化需要填写有效的用户 ID。';
    }
    return null;
  };

  const runNormalization = async (): Promise<void> => {
    const validationError = validateNormalization();
    if (validationError) {
      setNormalizationError(validationError);
      return;
    }

    setNormalizing(true);
    setNormalizationError(null);
    setNormalizationNotice(null);
    try {
      const response = await contentEventsAdminApi.normalize(
        normalizationPayload,
        crypto.randomUUID(),
      );
      setNormalizationNotice(
        `${response.mode === 'shadow' ? '影子运行' : '写入运行'}已完成：${resultSummary(response)}`,
      );
      if (response.mode === 'write') {
        await loadReviews();
      }
    } catch (requestError) {
      const apiError = requestError as ApiError;
      setNormalizationError(
        apiError.status === 409
          ? '已有相同范围的归一化任务正在运行，请稍后刷新再试。'
          : errorMessage(requestError, '归一化任务启动失败'),
      );
    } finally {
      setNormalizing(false);
      setShowWriteConfirmation(false);
    }
  };

  const submitNormalization = (): void => {
    const validationError = validateNormalization();
    if (validationError) {
      setNormalizationError(validationError);
      return;
    }
    if (mode === 'write') {
      setShowWriteConfirmation(true);
      return;
    }
    void runNormalization();
  };

  if (authLoading) return <LoadingState label="正在验证管理员权限…" />;
  if (currentUser?.role !== 'admin') {
    return (
      <AdminPageShell>
        <AdminNoticeBanner tone="red">需要管理员权限</AdminNoticeBanner>
      </AdminPageShell>
    );
  }

  return (
    <AdminPageShell maxWidth={1480}>
      <AdminPageHeader
        title="内容事件治理"
        icon={GitMerge}
        description="审核同事件消息关系，并以可回滚的影子模式验证近期内容归一化。"
        actions={
          <Button
            type="button"
            onClick={() => void loadReviews()}
            disabled={loading || rowBusyId !== null}
            aria-label="刷新内容事件审核队列"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            刷新
          </Button>
        }
      />

      <Panel className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-black text-gray-900">近期内容归一化</h2>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              默认影子运行，只记录判断结果，不改事件真源或旧版兼容投影。
            </p>
          </div>
          <Badge tone={mode === 'shadow' ? 'primary' : 'red'}>
            {mode === 'shadow' ? 'SHADOW 安全模式' : 'WRITE 写入模式'}
          </Badge>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="space-y-1 text-xs font-bold text-gray-600">
            <span>时间窗口（小时）</span>
            <input
              type="number"
              min={1}
              max={720}
              step={1}
              value={hours}
              onChange={(event) => setHours(Number(event.target.value))}
              disabled={normalizing}
              className="h-9 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm font-normal text-gray-800 outline-none transition focus:border-primary"
            />
          </label>

          <label className="space-y-1 text-xs font-bold text-gray-600">
            <span>数据范围</span>
            <select
              value={scope}
              onChange={(event) => {
                setScope(event.target.value as ContentEventNormalizationScope);
                if (event.target.value === 'public') setOwnerUserId('');
              }}
              disabled={normalizing}
              className="h-9 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm font-normal text-gray-800 outline-none transition focus:border-primary"
            >
              <option value="public">公共内容</option>
              <option value="user">指定用户</option>
            </select>
          </label>

          <label className="space-y-1 text-xs font-bold text-gray-600">
            <span>用户 ID</span>
            <input
              type="number"
              min={1}
              step={1}
              value={ownerUserId}
              onChange={(event) => setOwnerUserId(event.target.value)}
              disabled={scope !== 'user' || normalizing}
              placeholder={scope === 'user' ? '必填' : '公共范围无需填写'}
              className="h-9 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm font-normal text-gray-800 outline-none transition focus:border-primary disabled:bg-gray-50 disabled:text-gray-400"
            />
          </label>

          <label className="space-y-1 text-xs font-bold text-gray-600">
            <span>运行模式</span>
            <select
              value={mode}
              onChange={(event) =>
                setMode(event.target.value as ContentEventNormalizationMode)
              }
              disabled={normalizing}
              className="h-9 w-full rounded-sm border border-gray-200 bg-white px-3 text-sm font-normal text-gray-800 outline-none transition focus:border-primary"
            >
              <option value="shadow">影子运行（推荐）</option>
              <option value="write">写入事件真源</option>
            </select>
          </label>

          <div className="flex items-end">
            <Button
              type="button"
              variant={mode === 'write' ? 'danger' : 'primary'}
              onClick={submitNormalization}
              disabled={normalizing}
              className="w-full"
            >
              <Play size={14} />
              {normalizing ? '运行中…' : '开始归一化'}
            </Button>
          </div>
        </div>

        {normalizationError && (
          <AdminNoticeBanner
            tone="red"
            className="mt-4"
            onClose={() => setNormalizationError(null)}
          >
            {normalizationError}
          </AdminNoticeBanner>
        )}
        {normalizationNotice && (
          <AdminNoticeBanner
            tone="teal"
            className="mt-4"
            onClose={() => setNormalizationNotice(null)}
          >
            {normalizationNotice}
          </AdminNoticeBanner>
        )}
      </Panel>

      <Panel className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-4 py-3">
          <div>
            <h2 className="text-sm font-black text-gray-900">关系审核队列</h2>
            <p className="mt-0.5 text-xs text-gray-500">
              服务端筛选与分页；每次提交均校验事件版本。
            </p>
          </div>
          <div
            role="tablist"
            aria-label="按审核状态筛选"
            className="flex flex-wrap gap-1 rounded-sm bg-gray-100 p-1"
          >
            {REVIEW_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                role="tab"
                aria-selected={reviewStatus === tab.value}
                onClick={() => {
                  setReviewStatus(tab.value);
                  setPage(1);
                  setNotice(null);
                }}
                className={cx(
                  'rounded-xs px-3 py-1.5 text-xs font-bold transition',
                  reviewStatus === tab.value
                    ? 'bg-white text-primary shadow-sm'
                    : 'text-gray-500 hover:text-gray-800',
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="px-4 pt-4">
            <AdminNoticeBanner tone="red" onClose={() => setError(null)}>
              {error}
            </AdminNoticeBanner>
          </div>
        )}
        {notice && (
          <div className="px-4 pt-4">
            <AdminNoticeBanner tone="teal" onClose={() => setNotice(null)}>
              {notice}
            </AdminNoticeBanner>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="min-w-[1240px] w-full border-collapse text-left">
            <thead className="bg-gray-50 text-[11px] font-black uppercase tracking-wide text-gray-500">
              <tr>
                <th scope="col" className="px-4 py-3">内容</th>
                <th scope="col" className="px-3 py-3">来源</th>
                <th scope="col" className="px-3 py-3">当前关系</th>
                <th scope="col" className="px-3 py-3">置信度</th>
                <th scope="col" className="px-3 py-3">判断理由</th>
                <th scope="col" className="px-3 py-3">匹配时间</th>
                <th scope="col" className="px-3 py-3">版本</th>
                <th scope="col" className="px-4 py-3">审核操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && reviews.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-500">
                    正在加载审核队列…
                  </td>
                </tr>
              ) : reviews.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <div className="font-bold text-gray-700">当前筛选下没有数据</div>
                    <div className="mt-1 text-xs text-gray-400">
                      可切换审核状态，或先执行一次影子归一化。
                    </div>
                  </td>
                </tr>
              ) : (
                reviews.map((item) => {
                  const draft = drafts[item.id] ?? {
                    relation: item.relation_type,
                    reason: '',
                  };
                  const busy = rowBusyId === item.id;
                  const statusMeta = REVIEW_STATUS_META[item.review_status];
                  return (
                    <tr key={item.id} className="align-top hover:bg-gray-50/70">
                      <td className="max-w-[260px] px-4 py-3">
                        <div className="line-clamp-2 text-sm font-bold leading-5 text-gray-900">
                          {item.title}
                        </div>
                        <div className="mt-1 font-mono text-[10px] text-gray-400">
                          content #{item.content_id} · event #{item.event_id}
                        </div>
                      </td>
                      <td className="max-w-[140px] px-3 py-3">
                        <div className="truncate text-xs font-bold text-gray-700">
                          {item.source_name || '未知来源'}
                        </div>
                        <div className="mt-1 text-[10px] text-gray-400">
                          {item.source_type || '-'}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <Badge tone={statusMeta.tone}>{statusMeta.label}</Badge>
                        <div className="mt-1.5 text-xs font-bold text-gray-700">
                          {RELATION_LABELS[item.relation_type]}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <span className="font-mono text-sm font-black text-gray-800">
                          {(item.confidence * 100).toFixed(1)}%
                        </span>
                        <div className="mt-1 text-[10px] text-gray-400">
                          {item.match_method || '-'}
                        </div>
                      </td>
                      <td className="max-w-[220px] px-3 py-3 text-xs leading-5 text-gray-600">
                        {item.reason || '暂无模型理由'}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs text-gray-500">
                        {formatDateTime(item.matched_at, true)}
                      </td>
                      <td className="px-3 py-3">
                        <Badge tone="neutral">v{item.event_version}</Badge>
                      </td>
                      <td className="w-[340px] px-4 py-3">
                        <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-2">
                          <select
                            value={draft.relation}
                            onChange={(event) =>
                              patchDraft(item.id, {
                                relation: event.target.value as ContentEventRelation,
                              })
                            }
                            disabled={busy || rowBusyId !== null}
                            aria-label={`选择「${item.title}」的事件关系`}
                            className="h-9 rounded-sm border border-gray-200 bg-white px-2 text-xs text-gray-700 outline-none focus:border-primary disabled:bg-gray-50"
                          >
                            {RELATION_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                          <input
                            type="text"
                            value={draft.reason}
                            onChange={(event) =>
                              patchDraft(item.id, { reason: event.target.value })
                            }
                            disabled={busy || rowBusyId !== null}
                            maxLength={2000}
                            aria-label={`填写「${item.title}」的审核理由`}
                            placeholder="填写审核理由（必填）"
                            className="h-9 min-w-0 rounded-sm border border-gray-200 bg-white px-2 text-xs text-gray-700 outline-none focus:border-primary disabled:bg-gray-50"
                          />
                        </div>
                        <div className="mt-2 flex justify-end gap-2">
                          <Button
                            type="button"
                            variant="danger"
                            onClick={() => void reviewMember(item, 'reject')}
                            disabled={rowBusyId !== null || !draft.reason.trim()}
                            aria-label={`拒绝「${item.title}」的事件关系`}
                            className="min-h-8 py-1.5"
                          >
                            <X size={13} />
                            拒绝
                          </Button>
                          <Button
                            type="button"
                            variant="success"
                            onClick={() => void reviewMember(item, 'accept')}
                            disabled={rowBusyId !== null || !draft.reason.trim()}
                            aria-label={`接受「${item.title}」的事件关系`}
                            className="min-h-8 py-1.5"
                          >
                            <Check size={13} />
                            {busy ? '提交中…' : '接受'}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-200 px-4 py-3">
          <div className="text-xs text-gray-500">
            {total === 0 ? '共 0 条' : `显示 ${pageStart}–${pageEnd}，共 ${total} 条`}
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={loading || page <= 1}
              aria-label="上一页审核数据"
            >
              上一页
            </Button>
            <span className="min-w-20 text-center text-xs font-bold text-gray-600">
              {page} / {totalPages}
            </span>
            <Button
              type="button"
              onClick={() =>
                setPage((current) => Math.min(totalPages, current + 1))
              }
              disabled={loading || page >= totalPages}
              aria-label="下一页审核数据"
            >
              下一页
            </Button>
          </div>
        </div>
      </Panel>

      {showWriteConfirmation && (
        <AdminModal
          title="确认写入内容事件真源？"
          onClose={() => {
            if (!normalizing) setShowWriteConfirmation(false);
          }}
          maxWidth={560}
        >
          <div className="flex items-start gap-3 rounded-sm border border-red-border bg-red-light p-4 text-red">
            <ShieldAlert size={20} className="mt-0.5 shrink-0" />
            <div>
              <div className="text-sm font-black">这是有数据副作用的运行模式</div>
              <p className="mt-1 text-xs font-bold leading-5">
                WRITE 会写入事件真源，并同步更新 legacy duplicate_of /
                similarity_score 兼容投影。请先用相同参数完成影子验证。
              </p>
            </div>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-3 rounded-sm bg-gray-50 p-4 text-xs">
            <div>
              <dt className="text-gray-400">时间窗口</dt>
              <dd className="mt-1 font-black text-gray-800">{hours} 小时</dd>
            </div>
            <div>
              <dt className="text-gray-400">数据范围</dt>
              <dd className="mt-1 font-black text-gray-800">
                {scope === 'public' ? '公共内容' : `用户 #${ownerUserId}`}
              </dd>
            </div>
          </dl>
          <AdminModalFooter>
            <Button
              type="button"
              onClick={() => setShowWriteConfirmation(false)}
              disabled={normalizing}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => void runNormalization()}
              disabled={normalizing}
            >
              <ShieldAlert size={14} />
              {normalizing ? '正在写入…' : '确认写入'}
            </Button>
          </AdminModalFooter>
        </AdminModal>
      )}
    </AdminPageShell>
  );
}
