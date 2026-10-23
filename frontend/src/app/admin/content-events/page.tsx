'use client';

/**
 * 内容事件治理（#125 v2 第二片：吃满数据密集页原语）。
 *
 * 审核队列由手写 table 迁移到 AdminTable（三态内建：骨架 / 内联错误+重试 /
 * 按审核状态区分文案的空态），操作列右侧粘性；接受 / 拒绝是本页仅有的两个
 * 行内动作（≤2 全部直显，无需「···」折叠菜单，与 contents 页同口径），
 * 拒绝属不可逆动作，先过 AdminModal 二次确认再提交。
 * 审核状态 / 页码 / 每页条数与 URL query 双向同步（两段式恢复）；
 * 分页换升级版 Pagination（后端 page_size 支持 1–200，档位 10/20/50）。
 * 审核成功走 toast，系统级错误（OCC 冲突 / 校验失败）与归一化结果摘要
 * 留 AdminNoticeBanner 持久可见。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  GitMerge,
  ListChecks,
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
import { AdminEmptyState, AdminTable, toast } from '@/components/admin';
import type { AdminTableColumn } from '@/components/admin';
import { Pagination } from '@/components/Pagination';
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

const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [10, 20, 50] as const;

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

// 空态文案按审核状态区分：pending 是队列视角（清空即好消息），其余状态
// 是归档视角（说明记录从哪来，主动作引导回待审队列）。
const EMPTY_STATE_BY_STATUS: Record<
  ContentEventReviewStatus,
  { title: string; description: string }
> = {
  pending: {
    title: '待审核队列已清空',
    description: '当前没有等待人工确认的事件关系，可刷新队列，或先执行一次影子归一化。',
  },
  auto: {
    title: '暂无自动通过的记录',
    description: '归一化引擎自动通过的关系会出现在这里。',
  },
  confirmed: {
    title: '暂无人工确认的记录',
    description: '接受过的关系会出现在这里。',
  },
  rejected: {
    title: '暂无已拒绝的记录',
    description: '拒绝过的关系会出现在这里。',
  },
};

// ─── URL query 同步（#125 与 sources / contents 页同口径）──
// 挂载时从 location.search 恢复初始状态；此后审核状态/页码/每页条数变化用
// history.replaceState 覆写 query——不产生历史记录、不触发导航，
// 刻意不用 useSearchParams 以避开 Suspense 边界。
// 默认值（待审核、第 1 页、每页 20）不写入 query，保持 URL 干净。

type ContentEventsQueryState = {
  page: number;
  pageSize: number;
  status: ContentEventReviewStatus;
};

function defaultContentEventsQueryState(): ContentEventsQueryState {
  return { page: 1, pageSize: DEFAULT_PAGE_SIZE, status: 'pending' };
}

function readInitialStateFromLocation(): ContentEventsQueryState {
  const defaults = defaultContentEventsQueryState();
  const sp = new URLSearchParams(window.location.search);
  const page = Math.max(1, Number.parseInt(sp.get('page') ?? '', 10) || 1);
  const rawPageSize = Number.parseInt(sp.get('page_size') ?? '', 10);
  const pageSize = (PAGE_SIZE_OPTIONS as readonly number[]).includes(rawPageSize)
    ? rawPageSize
    : DEFAULT_PAGE_SIZE;
  const rawStatus = sp.get('status') ?? 'pending';
  const status = REVIEW_TABS.some((tab) => tab.value === rawStatus)
    ? (rawStatus as ContentEventReviewStatus)
    : defaults.status;
  return { page, pageSize, status };
}

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

// ─── 破坏性动作二次确认 ───
// 拒绝（不可逆）统一收口到这一个确认弹窗；接受不拦截。

interface ConfirmState {
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  onConfirm: () => void | Promise<void>;
}

export default function ContentEventsAdminPage() {
  const { currentUser, authLoading } = useAppContext();
  // 两段式恢复：SSR 与首帧一律用默认值（防 hydration mismatch——惰性读
  // location 会在带参数直达时让服务端/客户端首帧不一致），挂载后再从 URL
  // 恢复一次；didRestore 门让首拉只发一次且 URL 不被默认值覆写清掉。
  const [initial] = useState(defaultContentEventsQueryState);
  const [reviewStatus, setReviewStatus] =
    useState<ContentEventReviewStatus>(initial.status);
  const [reviews, setReviews] = useState<ContentEventReviewItem[]>([]);
  const [drafts, setDrafts] = useState<Record<number, ReviewDraft>>({});
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(initial.pageSize);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [rowBusyId, setRowBusyId] = useState<number | null>(null);
  // 列表加载失败 → AdminTable 内联错误 + 重试；审核动作类错误（OCC 冲突等）
  // 仍走 AdminNoticeBanner 持久可见
  const [listError, setListError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const requestSequence = useRef(0);
  const [didRestore, setDidRestore] = useState(false);

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
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const loadReviews = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setListError(null);
    try {
      const response = await contentEventsAdminApi.listReviews({
        page,
        page_size: pageSize,
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
      setListError(errorMessage(requestError, '审核队列加载失败'));
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [page, pageSize, reviewStatus]);

  // 挂载后恢复 URL 状态（两段式的第二段），随后放行首拉
  useEffect(() => {
    const restored = readInitialStateFromLocation();
    if (restored.page !== initial.page) setPage(restored.page);
    if (restored.pageSize !== initial.pageSize) setPageSize(restored.pageSize);
    if (restored.status !== initial.status) setReviewStatus(restored.status);
    setDidRestore(true);
    // 仅挂载时执行一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 首拉与筛选/页码/每页条数变化的重拉；恢复完成前不拉，
  // 避免默认值先打一发再被 URL 值重打的 double fetch
  useEffect(() => {
    if (!didRestore) return;
    if (!authLoading && currentUser?.role === 'admin') {
      void loadReviews();
    }
  }, [didRestore, authLoading, currentUser, loadReviews]);

  // URL query 覆写：与恢复逻辑对称，非默认值才落 query（恢复完成前不写，
  // 防止把直达 URL 清成默认态）
  useEffect(() => {
    if (!didRestore) return;
    const sp = new URLSearchParams();
    if (reviewStatus !== 'pending') sp.set('status', reviewStatus);
    if (page > 1) sp.set('page', String(page));
    if (pageSize !== DEFAULT_PAGE_SIZE) sp.set('page_size', String(pageSize));
    const qs = sp.toString();
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
  }, [didRestore, reviewStatus, page, pageSize]);

  // 恢复的页码可能越过当前筛选下的总页数（书签里存着 page=99），收回最后一页
  useEffect(() => {
    if (!loading && page > totalPages) setPage(totalPages);
  }, [loading, page, totalPages]);

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
      // 归一化结果摘要可能含部分失败明细，留横幅持久可见，不走转瞬即逝的 toast
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
      // 按钮在理由为空时已禁用，这里是兜底（防其它入口绕过）
      setActionError('请先填写审核理由。');
      return;
    }

    setRowBusyId(item.id);
    setActionError(null);
    try {
      await contentEventsAdminApi.reviewMember(item.id, {
        decision,
        ...(decision === 'accept'
          ? { relation_type: draft?.relation ?? item.relation_type }
          : {}),
        reason,
        expected_version: item.event_version,
      });
      toast.success(
        decision === 'accept'
          ? `已确认「${item.title}」的事件关系`
          : `已拒绝「${item.title}」的事件关系`,
      );
      if (reviews.length === 1 && page > 1) {
        setPage((current) => current - 1);
      } else {
        await loadReviews();
      }
    } catch (requestError) {
      const apiError = requestError as ApiError;
      if (apiError.status === 409) {
        setActionError('事件版本已被其他任务或管理员更新，请刷新队列后重新审核。');
      } else {
        setActionError(errorMessage(requestError, '审核操作失败'));
      }
    } finally {
      setRowBusyId(null);
    }
  };

  // 拒绝属不可逆动作：先过 AdminModal 二次确认，确认后才提交
  const requestRejectReview = (item: ContentEventReviewItem): void => {
    const reason = drafts[item.id]?.reason.trim() ?? '';
    if (!reason) {
      setActionError('请先填写审核理由。');
      return;
    }
    setConfirmState({
      title: '拒绝事件关系',
      message: (
        <>
          将拒绝「<b>{item.title}</b>」与事件{' '}
          <span className="font-mono">#{item.event_id}</span>{' '}
          的关系判定，提交后移入「已拒绝」且不可撤销。
          <span className="mt-1 block break-all text-ink-500">
            审核理由：{reason}
          </span>
        </>
      ),
      confirmLabel: '确认拒绝',
      onConfirm: () => reviewMember(item, 'reject'),
    });
  };

  // ─── 确认弹窗执行 ───
  const runConfirm = async () => {
    if (!confirmState || confirmBusy) return;
    setConfirmBusy(true);
    try {
      await confirmState.onConfirm();
      setConfirmState(null);
    } catch {
      // 各 onConfirm 自带错误上报（AdminNoticeBanner），这里只防止确认框卡死
    } finally {
      setConfirmBusy(false);
    }
  };

  const handlePageSizeChange = (size: number): void => {
    setPageSize(size);
    setPage(1);
  };

  const switchReviewStatus = (status: ContentEventReviewStatus): void => {
    setReviewStatus(status);
    setPage(1);
  };

  if (authLoading) return <LoadingState label="正在验证管理员权限…" />;
  if (currentUser?.role !== 'admin') {
    return (
      <AdminPageShell>
        <AdminNoticeBanner tone="red">需要管理员权限</AdminNoticeBanner>
      </AdminPageShell>
    );
  }

  // ─── 列定义（操作列右侧粘性）──
  // 审核意见列承载行内关系下拉 + 理由输入（保留逐条快审的流）；
  // 操作列只放接受 / 拒绝两个高频动作。

  const columns: AdminTableColumn<ContentEventReviewItem>[] = [
    {
      key: 'title',
      header: '内容',
      render: (item) => (
        <div className="min-w-0 max-w-[280px]">
          <span className="block truncate text-[13px] font-bold text-ink-900" title={item.title}>
            {item.title}
          </span>
          <span className="mt-0.5 block truncate font-mono text-[10px] text-ink-500">
            content #{item.content_id} · event #{item.event_id}
          </span>
        </div>
      ),
    },
    {
      key: 'source',
      header: '来源',
      width: 130,
      render: (item) => (
        <div className="min-w-0">
          <span
            className="block truncate text-xs font-bold text-ink-700"
            title={item.source_name ?? undefined}
          >
            {item.source_name || '未知来源'}
          </span>
          <span className="mt-0.5 block truncate text-[10px] text-ink-500">
            {item.source_type || '-'}
          </span>
        </div>
      ),
    },
    {
      key: 'relation',
      header: '当前关系',
      width: 132,
      render: (item) => {
        const statusMeta = REVIEW_STATUS_META[item.review_status];
        return (
          <div className="min-w-0">
            <Badge tone={statusMeta.tone}>{statusMeta.label}</Badge>
            <div className="mt-1 text-xs font-bold text-ink-700">
              {RELATION_LABELS[item.relation_type]}
            </div>
          </div>
        );
      },
    },
    {
      key: 'confidence',
      header: '置信度',
      width: 96,
      render: (item) => (
        <div className="min-w-0">
          <span className="font-mono text-[13px] font-black text-ink-900">
            {(item.confidence * 100).toFixed(1)}%
          </span>
          {item.match_method && (
            <span
              className="mt-0.5 block truncate text-[10px] text-ink-500"
              title={item.match_method}
            >
              {item.match_method}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'reason',
      header: '判断理由',
      width: 200,
      render: (item) => (
        <span
          className="block max-w-[200px] text-xs leading-5 text-ink-700"
          title={item.reason ?? undefined}
        >
          {item.reason || '暂无模型理由'}
        </span>
      ),
    },
    {
      key: 'matched_at',
      header: '匹配时间',
      width: 118,
      render: (item) => (
        <span className="whitespace-nowrap text-xs text-ink-500">
          {formatDateTime(item.matched_at, true)}
        </span>
      ),
    },
    {
      key: 'version',
      header: '版本',
      width: 64,
      render: (item) => <Badge tone="neutral">v{item.event_version}</Badge>,
    },
    {
      key: 'draft',
      mobileAlwaysVisible: true,
      header: '审核意见',
      width: 330,
      render: (item) => {
        const draft = drafts[item.id] ?? {
          relation: item.relation_type,
          reason: '',
        };
        return (
          <div className="grid w-full grid-cols-[118px_minmax(0,1fr)] gap-1.5">
            <select
              value={draft.relation}
              onChange={(event) =>
                patchDraft(item.id, {
                  relation: event.target.value as ContentEventRelation,
                })
              }
              disabled={rowBusyId !== null}
              aria-label={`选择「${item.title}」的事件关系`}
              className="h-8 cursor-pointer rounded-xs border border-ink-200 bg-white px-1.5 text-xs text-ink-700 focus:border-admin-accent focus:outline-none disabled:bg-ink-100 disabled:text-ink-400"
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
              disabled={rowBusyId !== null}
              maxLength={2000}
              aria-label={`填写「${item.title}」的审核理由`}
              placeholder="审核理由（必填）"
              className="h-8 min-w-0 rounded-xs border border-ink-200 bg-white px-2 text-xs text-ink-700 placeholder:text-ink-500 focus:border-admin-accent focus:outline-none disabled:bg-ink-100 disabled:text-ink-400"
            />
          </div>
        );
      },
    },
    {
      key: 'actions',
      header: '操作',
      width: 156,
      sticky: 'right',
      // 本页核心动作就接受 / 拒绝两个（≤2 全部直显，无需「···」折叠菜单，
      // 与 contents 页同口径）；拒绝点开后先过 AdminModal 二次确认。
      render: (item) => {
        const draft = drafts[item.id] ?? {
          relation: item.relation_type,
          reason: '',
        };
        const busy = rowBusyId === item.id;
        const inputsReady = draft.reason.trim().length > 0;
        return (
          <div className="flex items-center justify-end gap-1.5">
            <Button
              type="button"
              variant="danger"
              onClick={() => requestRejectReview(item)}
              disabled={rowBusyId !== null || !inputsReady}
              aria-label={`拒绝「${item.title}」的事件关系`}
              className="min-h-8 px-2.5 py-1 text-[11px]"
            >
              <X size={13} />
              拒绝
            </Button>
            <Button
              type="button"
              variant="success"
              onClick={() => void reviewMember(item, 'accept')}
              disabled={rowBusyId !== null || !inputsReady}
              aria-label={`接受「${item.title}」的事件关系`}
              className="min-h-8 px-2.5 py-1 text-[11px]"
            >
              <Check size={13} />
              {busy ? '提交中…' : '接受'}
            </Button>
          </div>
        );
      },
    },
  ];

  const emptyMeta = EMPTY_STATE_BY_STATUS[reviewStatus];

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

      {/* 审核队列头部：标题 + 审核状态分段控件（tab 语义），与 URL query 同步 */}
      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
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
              onClick={() => switchReviewStatus(tab.value)}
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

      {/* 审核动作类错误（OCC 冲突 / 校验失败）：系统级消息留横幅持久可见 */}
      {actionError && (
        <AdminNoticeBanner
          tone="red"
          className="mt-3"
          onClose={() => setActionError(null)}
        >
          {actionError}
        </AdminNoticeBanner>
      )}

      {/* 三态（骨架 / 内联错误+重试 / 空态）由 AdminTable 内建，页面层不自造 */}
      <AdminTable
        columns={columns}
        rows={reviews}
        rowKey={(item) => item.id}
        loading={loading}
        error={listError}
        onRetry={() => void loadReviews()}
        empty={
          <AdminEmptyState
            compact
            icon={ListChecks}
            title={emptyMeta.title}
            description={emptyMeta.description}
            action={
              reviewStatus === 'pending' ? (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => void loadReviews()}
                  disabled={loading}
                >
                  刷新队列
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => switchReviewStatus('pending')}
                >
                  查看待审核
                </Button>
              )
            }
          />
        }
        minWidth={1360}
      />

      {/* 分页：后端 /admin/content-events/reviews 支持 page_size（1–200），
          每页条数选择器（10/20/50，默认 20）随之落地 */}
      {!loading && total > 0 && (
        <Pagination
          page={page}
          totalPages={totalPages}
          onPage={setPage}
          pageSize={pageSize}
          pageSizeOptions={PAGE_SIZE_OPTIONS}
          onPageSizeChange={handlePageSizeChange}
          summary={
            <>
              第{' '}
              <b className="font-mono">
                {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)}
              </b>{' '}
              条，共 {total} 条
            </>
          }
        />
      )}

      {/* 拒绝（不可逆）二次确认弹窗 */}
      {confirmState && (
        <AdminModal
          title={confirmState.title}
          onClose={() => {
            if (!confirmBusy) setConfirmState(null);
          }}
          maxWidth={520}
        >
          <p className="text-[13px] leading-6 text-ink-700">{confirmState.message}</p>
          <AdminModalFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setConfirmState(null)}
              disabled={confirmBusy}
              className="px-5"
            >
              取消
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => void runConfirm()}
              disabled={confirmBusy}
              className="px-5"
            >
              {confirmBusy ? '处理中…' : confirmState.confirmLabel}
            </Button>
          </AdminModalFooter>
        </AdminModal>
      )}

      {/* 写入确认弹窗：纯确认无输入项，isDirty 不适用 */}
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
                WRITE 会写入唯一的事件真源，并立即影响用户侧的事件折叠与证据口径。
                请先用相同参数完成影子验证。
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
