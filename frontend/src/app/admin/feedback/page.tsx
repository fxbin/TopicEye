'use client';

/**
 * 反馈工作台（#125 v2 第二片之一：数据密集页原语吃满）。
 *
 * 管理端「全部反馈处理」由手写卡片列表迁移到 AdminTable（三态内建：骨架 /
 * 内联错误+重试 / 空态区分「无匹配筛选」与「暂无反馈」），操作列右侧粘性：
 * 高频动作（确认 / 处理中）直显，已修复 / 关闭收进行尾「···」菜单——这两个
 * 不可逆流转先过二次确认弹窗。筛选换 AdminFilters + AdminFilterChips
 * （状态 / 严重度 / 模块三个下拉；listIssues 没有关键词搜索，搜索框按
 * AdminFilters 必传契约隐藏）。分页按 listIssues 的 limit/offset 模型换算页码，
 * totalPages = ceil(total / limit)；筛选 / 页码 / 每页条数与 URL query 双向同步
 * （默认值不落 query）。处理成功走 toast，系统级错误留 AdminNoticeBanner，
 * 列表加载失败走表格内联重试。
 *
 * 入口菜单已迁往 /changelog，本页仍可直达（管理员深链），提交反馈 /
 * 我的反馈 / 更新路线与记录等既有能力全部保留。
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  CircleDot,
  ClipboardCheck,
  Clock3,
  Flag,
  Loader2,
  MessageSquareWarning,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Wrench,
  XCircle,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, PanelTitle, cx, type Tone } from '@/components/ui';
import { ErrorState, LoadingState } from '@/components/StateView';
import { AdminModal, AdminModalFooter, AdminNoticeBanner, AdminPageHeader, AdminPageShell } from '@/components/admin-ui';
import {
  AdminEmptyState,
  AdminFilterChips,
  AdminFilters,
  AdminTable,
  toast,
} from '@/components/admin';
import type { AdminFilterChip, AdminTableColumn } from '@/components/admin';
import { Pagination } from '@/components/Pagination';
import { useFetch } from '@/hooks/useFetch';
import {
  productFeedbackApi,
  type IssueFeedbackItem,
  type IssueFeedbackSeverity,
  type IssueFeedbackStatus,
  type ProductUpdateItem,
  type ProductUpdateStatus,
} from '@/lib/api';
import { formatDateTime as formatTime, formatDate } from '@/lib/datetime';
import {
  ISSUE_STATUS_LABELS,
  ISSUE_STATUS_TONES,
  SEVERITY_LABELS,
  SEVERITY_TONES,
  UPDATE_KIND_LABELS,
  UPDATE_STATUS_LABELS,
  UPDATE_STATUS_TONES,
} from '@/lib/product-feedback-labels';

// 注：Tone 类型与 product-feedback 标签映射已收敛到公共模块：
// - Tone ← @/components/ui
// - 标签映射 ← @/lib/product-feedback-labels（修复 R9 值冲突）


const AREA_OPTIONS = [
  { value: 'analysis', label: 'AI 分析' },
  { value: 'trending', label: '趋势/信源' },
  { value: 'frontend', label: '界面体验' },
  { value: 'account', label: '账号/权限' },
  { value: 'general', label: '其他' },
];

const ISSUE_STATUS_KEYS = Object.keys(ISSUE_STATUS_LABELS) as IssueFeedbackStatus[];
const SEVERITY_KEYS = Object.keys(SEVERITY_LABELS) as IssueFeedbackSeverity[];

// listIssues 的 limit 上限 300（backend Query(ge=1, le=300)），10/20/50 档位全部合法
const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [10, 20, 50] as const;

// ─── URL query 同步（#125 v2，两段式）──
// 挂载时从 location.search 恢复初始状态；此后筛选/页码/每页条数变化用
// history.replaceState 覆写 query——不产生历史记录、不触发导航，
// 刻意不用 useSearchParams 以避开 Suspense 边界（与 sources/contents 同口径）。
// 默认值（第 1 页、每页 20、无筛选）不写入 query，保持 URL 干净。
// listIssues 是 limit/offset 模型，URL 落页码（page），请求时换算 offset。

type FeedbackQueryState = {
  page: number;
  pageSize: number;
  status: IssueFeedbackStatus | '';
  severity: IssueFeedbackSeverity | '';
  area: string;
};

function defaultFeedbackQueryState(): FeedbackQueryState {
  return { page: 1, pageSize: DEFAULT_PAGE_SIZE, status: '', severity: '', area: '' };
}

function readInitialStateFromLocation(): FeedbackQueryState {
  const defaults = defaultFeedbackQueryState();
  const sp = new URLSearchParams(window.location.search);
  const page = Math.max(1, Number.parseInt(sp.get('page') ?? '', 10) || 1);
  const rawPageSize = Number.parseInt(sp.get('page_size') ?? '', 10);
  const pageSize = (PAGE_SIZE_OPTIONS as readonly number[]).includes(rawPageSize)
    ? rawPageSize
    : DEFAULT_PAGE_SIZE;
  const rawStatus = sp.get('status') ?? '';
  const rawSeverity = sp.get('severity') ?? '';
  const rawArea = sp.get('area') ?? '';
  return {
    page,
    pageSize,
    status: (ISSUE_STATUS_KEYS as readonly string[]).includes(rawStatus)
      ? (rawStatus as IssueFeedbackStatus)
      : defaults.status,
    severity: (SEVERITY_KEYS as readonly string[]).includes(rawSeverity)
      ? (rawSeverity as IssueFeedbackSeverity)
      : defaults.severity,
    area: AREA_OPTIONS.some((option) => option.value === rawArea) ? rawArea : defaults.area,
  };
}

function toneForBadge(tone: Tone): 'neutral' | 'primary' | 'teal' | 'amber' | 'purple' | 'red' {
  return tone;
}

function areaLabel(area: string): string {
  return AREA_OPTIONS.find((option) => option.value === area)?.label || area;
}

function reporterLabel(issue: IssueFeedbackItem): string {
  return issue.reporter_name || issue.reporter_email || (issue.user_id ? `用户 ${issue.user_id}` : '匿名用户');
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

// ─── 行尾「···」菜单（与 sources 页同口径）──
// 高频动作（≤2 个）之外的行操作收进这里。键盘可达：打开后焦点移入首项，
// ↑/↓ 在菜单项间移动，Esc 关闭并还焦给触发按钮，点击菜单外任意处关闭。
// 菜单用 fixed 定位挂在视口坐标上——否则会被表格 overflow-x-auto 滚动容器裁剪。

interface RowMenuItem {
  key: string;
  label: string;
  icon: LucideIcon;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

function RowActionsMenu({ label, items }: { label: string; items: RowMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const menuRef = React.useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  const openMenu = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPos({ top: rect.bottom + 4, left: rect.right });
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    // 打开后把焦点移进菜单，键盘用户不用再 Tab 一次
    const frame = window.requestAnimationFrame(() => {
      menuRef.current
        ?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')
        ?.focus();
    });
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    // 任何滚动/缩放都收回菜单：fixed 菜单不跟随滚动，悬空比关闭更糟
    const close = () => setOpen(false);
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (open ? setOpen(false) : openMenu())}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        className="flex h-7 w-7 items-center justify-center rounded-xs border border-transparent text-ink-500 transition hover:border-ink-200 hover:bg-white hover:text-ink-900"
      >
        <MoreHorizontal size={15} strokeWidth={2} />
      </button>
      {open && pos && (
        <div
          ref={menuRef}
          role="menu"
          aria-label={label}
          style={{ position: 'fixed', top: pos.top, left: pos.left, transform: 'translateX(-100%)' }}
          className="z-50 min-w-[148px] rounded-xs border border-ink-200 bg-white p-1 shadow-[0_8px_24px_rgba(15,23,42,0.12)]"
          onKeyDown={(event) => {
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
            event.preventDefault();
            const buttons = Array.from(
              menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [],
            );
            if (buttons.length === 0) return;
            const activeIndex = buttons.findIndex((button) => button === document.activeElement);
            const nextIndex =
              event.key === 'ArrowDown'
                ? (activeIndex + 1) % buttons.length
                : (activeIndex - 1 + buttons.length) % buttons.length;
            buttons[nextIndex]?.focus();
          }}
        >
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
                className={cx(
                  'flex w-full items-center gap-2 rounded-xs px-2.5 py-1.5 text-left text-xs transition disabled:cursor-not-allowed disabled:opacity-50',
                  item.danger ? 'text-red-600 hover:bg-red-light' : 'text-ink-700 hover:bg-ink-100',
                )}
              >
                <Icon size={13} strokeWidth={2} aria-hidden="true" />
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── 不可逆流转二次确认 ───
// 状态机里的 fixed / closed 不可逆（对提交人终态呈现），统一收口到这一个
// 确认弹窗；triaged / in_progress 可自由流转，不拦截。

interface ConfirmState {
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  onConfirm: () => void | Promise<void>;
}

// ─── Page Component ───

export default function FeedbackPage() {
  const { currentUser, authLoading } = useAppContext();
  const isAdmin = currentUser?.role === 'admin';
  const [savingIssue, setSavingIssue] = useState(false);
  // 正在流转的行 + 目标状态（行内按钮据此显示 spinner）
  const [issueUpdating, setIssueUpdating] = useState<{ id: number; status: IssueFeedbackStatus } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // 两段式恢复：SSR 与首帧一律用默认值（防 hydration mismatch——惰性读
  // location 会在带参数直达时让服务端/客户端首帧不一致），挂载后再从 URL
  // 恢复一次；didRestore 门让首拉只发一次且 URL 不被默认值覆写清掉。
  const [initial] = useState(defaultFeedbackQueryState);
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(initial.pageSize);
  const [filterStatus, setFilterStatus] = useState<IssueFeedbackStatus | ''>(initial.status);
  const [filterSeverity, setFilterSeverity] = useState<IssueFeedbackSeverity | ''>(initial.severity);
  const [filterArea, setFilterArea] = useState(initial.area);
  const [didRestore, setDidRestore] = useState(false);

  // 挂载后恢复 URL 状态（两段式的第二段），随后放行管理端列表首拉
  useEffect(() => {
    const restored = readInitialStateFromLocation();
    if (restored.page !== initial.page) setPage(restored.page);
    if (restored.pageSize !== initial.pageSize) setPageSize(restored.pageSize);
    if (restored.status !== initial.status) setFilterStatus(restored.status);
    if (restored.severity !== initial.severity) setFilterSeverity(restored.severity);
    if (restored.area !== initial.area) setFilterArea(restored.area);
    setDidRestore(true);
    // 仅挂载时执行一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 页面基础数据（我的反馈 + 更新记录）：不随筛选翻页变化，独立于管理端列表
  type PagePayload = {
    myIssues: IssueFeedbackItem[];
    myOpen: number;
    myFixed: number;
    updates: ProductUpdateItem[];
  };
  const { data: pageData, loading: pageLoading, error: pageError, refetch: refetchPage } = useFetch<PagePayload>(
    async () => {
      const [mine, updateList] = await Promise.all([
        currentUser ? productFeedbackApi.listMine({ limit: 80 }) : Promise.resolve(null),
        productFeedbackApi.listUpdates({ limit: 160 }),
      ]);
      return {
        myIssues: mine?.items || [],
        myOpen: mine?.open_count || 0,
        myFixed: mine?.fixed_count || 0,
        updates: updateList.items || [],
      };
    },
    [currentUser],
    { enabled: !authLoading },
  );

  // 管理端全部反馈列表：筛选 / 翻页只影响这块的三态，不动页面其它区块。
  // limit/offset 模型——页码换算 offset，恢复完成前不拉（防默认值 double fetch）
  const { data: issueData, loading: issueLoading, error: issueError, refetch: refetchIssues } = useFetch(
    async () => {
      if (!isAdmin) return null;
      return productFeedbackApi.listIssues({
        status: filterStatus,
        severity: filterSeverity,
        area: filterArea,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });
    },
    [isAdmin, filterStatus, filterSeverity, filterArea, page, pageSize],
    { enabled: !authLoading && isAdmin && didRestore },
  );

  const myIssues = pageData?.myIssues ?? [];
  const updates = pageData?.updates ?? [];
  const allIssues = issueData?.items ?? [];
  const issueTotal = issueData?.total ?? 0;
  const issueOpenCount = issueData?.open_count ?? 0;
  const issueFixedCount = issueData?.fixed_count ?? 0;
  const totalPages = Math.max(1, Math.ceil(issueTotal / pageSize));

  // URL query 覆写：与恢复逻辑对称，非默认值才落 query（恢复完成前不写，
  // 防止把直达 URL 清成默认态）
  useEffect(() => {
    if (!didRestore) return;
    const sp = new URLSearchParams();
    if (filterStatus) sp.set('status', filterStatus);
    if (filterSeverity) sp.set('severity', filterSeverity);
    if (filterArea) sp.set('area', filterArea);
    if (page > 1) sp.set('page', String(page));
    if (pageSize !== DEFAULT_PAGE_SIZE) sp.set('page_size', String(pageSize));
    const qs = sp.toString();
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
  }, [didRestore, filterStatus, filterSeverity, filterArea, page, pageSize]);

  // 恢复的页码可能越过当前筛选下的总页数（书签里存着 page=99），收回最后一页
  useEffect(() => {
    if (!issueLoading && page > totalPages) setPage(totalPages);
  }, [issueLoading, page, totalPages]);

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
    try {
      await productFeedbackApi.createIssue({
        title: issueForm.title.trim(),
        description: issueForm.description.trim(),
        area: issueForm.area,
        severity: issueForm.severity,
      });
      setIssueForm({ title: '', area: 'analysis', severity: 'medium', description: '' });
      toast.success('反馈已提交，后台会在处理后更新状态。');
      await Promise.all([refetchPage(), refetchIssues()]);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '提交反馈失败');
    } finally {
      setSavingIssue(false);
    }
  };

  // ─── 确认弹窗执行 ───
  const runConfirm = async () => {
    if (!confirmState || confirmBusy) return;
    setConfirmBusy(true);
    try {
      await confirmState.onConfirm();
      setConfirmState(null);
    } catch {
      // 各 onConfirm 自带错误上抛（AdminNoticeBanner），这里只防止确认框卡死
    } finally {
      setConfirmBusy(false);
    }
  };

  // ─── 状态流转（API 语义与迁移前一致：fixed 无说明时默认补一条修复备注） ───
  const runUpdateIssueStatus = async (issue: IssueFeedbackItem, status: IssueFeedbackStatus) => {
    setIssueUpdating({ id: issue.id, status });
    setFormError(null);
    try {
      await productFeedbackApi.updateIssue(issue.id, {
        status,
        resolution_note: status === 'fixed' ? issue.resolution_note || '相关问题已完成修复。' : issue.resolution_note || null,
      });
      toast.success(
        status === 'fixed' ? '已标记为修复。' : status === 'closed' ? '反馈已关闭。' : '反馈状态已更新。',
      );
      await Promise.all([refetchIssues(), refetchPage()]);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '更新反馈状态失败');
    } finally {
      setIssueUpdating(null);
    }
  };

  // fixed / closed 不可逆：先过二次确认
  const requestIrreversibleStatus = (issue: IssueFeedbackItem, status: 'fixed' | 'closed') => {
    setConfirmState({
      title: status === 'fixed' ? '标记为已修复' : '关闭反馈',
      message: status === 'fixed' ? (
        <>
          确定「<b>{issue.title}</b>」已完成修复吗？标记后对提交人显示为已修复；
          未填过处理说明时会默认补一条「相关问题已完成修复。」。
        </>
      ) : (
        <>
          确定关闭「<b>{issue.title}</b>」吗？关闭表示不再跟进该反馈，之后仍可重新流转状态。
        </>
      ),
      confirmLabel: status === 'fixed' ? '标记已修复' : '关闭反馈',
      onConfirm: () => runUpdateIssueStatus(issue, status),
    });
  };

  // ─── 筛选与 chips ───

  // listIssues 只有 status/severity/area 三个枚举筛选，没有关键词搜索能力；
  // AdminFilters 的搜索为可选契约（searchValue/onSearchChange 不传即不渲染搜索框）

  const handleStatusChange = (value: IssueFeedbackStatus | '') => {
    setFilterStatus(value);
    setPage(1);
  };

  const handleSeverityChange = (value: IssueFeedbackSeverity | '') => {
    setFilterSeverity(value);
    setPage(1);
  };

  const handleAreaChange = (value: string) => {
    setFilterArea(value);
    setPage(1);
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setPage(1);
  };

  const clearAllFilters = () => {
    setFilterStatus('');
    setFilterSeverity('');
    setFilterArea('');
    setPage(1);
  };

  const hasActiveFilters = filterStatus !== '' || filterSeverity !== '' || filterArea !== '';

  const filterChips: AdminFilterChip[] = [];
  if (filterStatus) {
    filterChips.push({
      key: 'status',
      label: `状态：${ISSUE_STATUS_LABELS[filterStatus]}`,
      onRemove: () => handleStatusChange(''),
    });
  }
  if (filterSeverity) {
    filterChips.push({
      key: 'severity',
      label: `严重度：${SEVERITY_LABELS[filterSeverity]}`,
      onRemove: () => handleSeverityChange(''),
    });
  }
  if (filterArea) {
    filterChips.push({
      key: 'area',
      label: `模块：${areaLabel(filterArea)}`,
      onRemove: () => handleAreaChange(''),
    });
  }

  // ─── 列定义（操作列右侧粘性；高频动作确认/处理中直显，其余收「···」菜单） ───

  const columns: AdminTableColumn<IssueFeedbackItem>[] = [
    {
      key: 'title',
      header: '标题',
      render: (issue) => (
        <div className="min-w-0">
          <span className="block max-w-[340px] truncate text-[13px] font-bold text-ink-900" title={issue.title}>
            {issue.title}
          </span>
          <span className="mt-0.5 block max-w-[340px] truncate text-[11px] text-ink-500" title={issue.description}>
            {issue.description}
          </span>
        </div>
      ),
    },
    {
      key: 'status',
      header: '状态',
      width: 128,
      render: (issue) => (
        <div className="min-w-0">
          <IssueStatusBadge status={issue.status} />
          {issue.resolution_note && (
            <span
              className="mt-0.5 block max-w-[110px] truncate text-[10px] leading-4 text-teal"
              title={issue.resolution_note}
            >
              {issue.resolution_note}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'severity',
      header: '严重度',
      width: 88,
      render: (issue) => <SeverityBadge severity={issue.severity} />,
    },
    {
      key: 'area',
      header: '模块',
      width: 104,
      render: (issue) => <Badge tone="neutral">{areaLabel(issue.area)}</Badge>,
    },
    {
      key: 'reporter',
      header: '提交人',
      width: 140,
      render: (issue) => (
        <span className="block max-w-[130px] truncate text-xs text-ink-700" title={reporterLabel(issue)}>
          {reporterLabel(issue)}
        </span>
      ),
    },
    {
      key: 'created',
      header: '提交时间',
      width: 148,
      render: (issue) => (
        <div className="min-w-0">
          <span className="block whitespace-nowrap font-mono text-xs text-ink-500">
            {formatTime(issue.created_at)}
          </span>
          {issue.fixed_at && (
            <span className="block whitespace-nowrap font-mono text-[10px] leading-4 text-teal">
              {formatTime(issue.fixed_at)} 修复
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'actions',
      header: '操作',
      width: 200,
      sticky: 'right',
      render: (issue) => {
        const updating = issueUpdating?.id === issue.id;
        return (
          <div className="flex items-center justify-end gap-1.5">
            {/* 高频动作 ≤2 直接可见：确认 / 处理中（可逆流转，不拦截） */}
            <Button
              type="button"
              variant="secondary"
              onClick={() => void runUpdateIssueStatus(issue, 'triaged')}
              disabled={updating || issue.status === 'triaged'}
              className="min-h-7 px-2.5 py-1 text-[11px]"
            >
              {issueUpdating?.id === issue.id && issueUpdating.status === 'triaged'
                ? <Loader2 size={13} className="animate-spin" />
                : <CircleDot size={13} />}
              确认
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void runUpdateIssueStatus(issue, 'in_progress')}
              disabled={updating || issue.status === 'in_progress'}
              className="min-h-7 px-2.5 py-1 text-[11px]"
            >
              {issueUpdating?.id === issue.id && issueUpdating.status === 'in_progress'
                ? <Loader2 size={13} className="animate-spin" />
                : <Wrench size={13} />}
              处理中
            </Button>
            {/* 不可逆流转收进行尾菜单，选中先过二次确认 */}
            <RowActionsMenu
              label={`「${issue.title}」的更多操作`}
              items={[
                {
                  key: 'fixed',
                  label: '标记已修复',
                  icon: CheckCircle2,
                  disabled: updating || issue.status === 'fixed',
                  onSelect: () => requestIrreversibleStatus(issue, 'fixed'),
                },
                {
                  key: 'closed',
                  label: '关闭反馈',
                  icon: XCircle,
                  disabled: updating || issue.status === 'closed',
                  onSelect: () => requestIrreversibleStatus(issue, 'closed'),
                },
              ]}
            />
          </div>
        );
      },
    },
  ];

  if (authLoading || pageLoading) {
    return (
      <AdminPageShell maxWidth={1280}>
        <LoadingState label="正在加载反馈工作台…" minHeight="200px" panel />
      </AdminPageShell>
    );
  }

  return (
    <AdminPageShell maxWidth={1280}>
      <AdminPageHeader
        title="反馈与更新"
        icon={MessageSquareWarning}
        description="反馈可以直接提交；更新路线和记录随版本发布内置展示。"
        actions={
          <Button
            type="button"
            onClick={() => {
              void refetchPage();
              void refetchIssues();
            }}
          >
            <RefreshCw size={14} />
            刷新
          </Button>
        }
      />

      {/* 系统级 / 变更类错误横幅；管理端列表加载失败走 AdminTable 内联错误 */}
      {formError && (
        <AdminNoticeBanner tone="red" onClose={() => setFormError(null)}>
          {formError}
        </AdminNoticeBanner>
      )}

      {pageError && (
        <ErrorState error={pageError} onRetry={() => void refetchPage()} panel />
      )}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {currentUser ? (
            <>
              <StatTile label="我的待处理" value={pageData?.myOpen ?? 0} icon={<CircleDot size={14} />} tone="amber" />
              <StatTile label="我的已修复" value={pageData?.myFixed ?? 0} icon={<CheckCircle2 size={14} />} tone="teal" />
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
          <div className="space-y-2">
            <PanelTitle
              icon={ShieldCheck}
              title="全部反馈处理"
              hint={`${issueOpenCount} 个待处理，${issueFixedCount} 个已修复`}
            />

            {/* 筛选行：状态下拉 + 严重度下拉 + 模块下拉；已选条件 chips 单移除 / 清空全部。
                listIssues 无关键词搜索能力——AdminFilters 搜索为可选契约，不传即不渲染 */}
            <AdminFilters>
              <select
                value={filterStatus}
                onChange={(e) => handleStatusChange(e.target.value as IssueFeedbackStatus | '')}
                aria-label="按状态筛选"
                className="h-9 cursor-pointer rounded-xs border border-ink-200 bg-white px-2 text-[13px] text-ink-900 focus:border-admin-accent focus:outline-none"
              >
                <option value="">全部状态</option>
                {ISSUE_STATUS_KEYS.map((status) => (
                  <option key={status} value={status}>{ISSUE_STATUS_LABELS[status]}</option>
                ))}
              </select>
              <select
                value={filterSeverity}
                onChange={(e) => handleSeverityChange(e.target.value as IssueFeedbackSeverity | '')}
                aria-label="按严重度筛选"
                className="h-9 cursor-pointer rounded-xs border border-ink-200 bg-white px-2 text-[13px] text-ink-900 focus:border-admin-accent focus:outline-none"
              >
                <option value="">全部严重度</option>
                {SEVERITY_KEYS.map((severity) => (
                  <option key={severity} value={severity}>{SEVERITY_LABELS[severity]}</option>
                ))}
              </select>
              <select
                value={filterArea}
                onChange={(e) => handleAreaChange(e.target.value)}
                aria-label="按模块筛选"
                className="h-9 cursor-pointer rounded-xs border border-ink-200 bg-white px-2 text-[13px] text-ink-900 focus:border-admin-accent focus:outline-none"
              >
                <option value="">全部模块</option>
                {AREA_OPTIONS.map((area) => (
                  <option key={area.value} value={area.value}>{area.label}</option>
                ))}
              </select>
            </AdminFilters>
            <AdminFilterChips chips={filterChips} onClearAll={clearAllFilters} />

            {/* 反馈列表：三态（骨架 / 内联错误+重试 / 空态）由 AdminTable 内建，操作列右侧粘性 */}
            <AdminTable
              columns={columns}
              rows={allIssues}
              rowKey={(issue) => issue.id}
              loading={issueLoading}
              error={issueError}
              onRetry={() => void refetchIssues()}
              empty={
                <AdminEmptyState
                  compact
                  icon={MessageSquareWarning}
                  title={hasActiveFilters ? '没有匹配的反馈' : '暂无反馈'}
                  description={hasActiveFilters ? '试试放宽状态 / 严重度 / 模块筛选' : '用户提交的问题反馈会出现在这里'}
                  action={
                    hasActiveFilters ? (
                      <Button type="button" variant="secondary" onClick={clearAllFilters}>
                        清空筛选
                      </Button>
                    ) : undefined
                  }
                />
              }
              minWidth={1040}
            />

            {/* 分页：limit/offset 模型换算页码；limit 上限 300，10/20/50 档位全部可接 */}
            {!issueLoading && issueTotal > 0 && (
              <Pagination
                page={page}
                totalPages={totalPages}
                onPage={(next) => setPage(typeof next === 'function' ? next(page) : next)}
                pageSize={pageSize}
                pageSizeOptions={PAGE_SIZE_OPTIONS}
                onPageSizeChange={handlePageSizeChange}
                summary={
                  <>
                    第 <b className="font-mono">{(page - 1) * pageSize + 1}-{Math.min(page * pageSize, issueTotal)}</b> 条，共 {issueTotal} 条
                  </>
                }
              />
            )}
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

      {/* 不可逆流转二次确认（已修复 / 关闭统一入口） */}
      {confirmState && (
        <AdminModal title={confirmState.title} onClose={() => { if (!confirmBusy) setConfirmState(null); }}>
          <p className="text-[13px] leading-6 text-ink-700">{confirmState.message}</p>
          <AdminModalFooter>
            <Button type="button" variant="secondary" onClick={() => setConfirmState(null)} disabled={confirmBusy} className="px-5">
              取消
            </Button>
            <Button type="button" variant="primary" onClick={() => void runConfirm()} disabled={confirmBusy} className="px-5">
              {confirmBusy ? '处理中…' : confirmState.confirmLabel}
            </Button>
          </AdminModalFooter>
        </AdminModal>
      )}
    </AdminPageShell>
  );
}

function IssueRow({ issue, compact = false }: { issue: IssueFeedbackItem; compact?: boolean }) {
  return (
    <div className={cx('rounded-sm border border-gray-200 bg-white', compact ? 'p-3.5' : 'border-0 p-0')}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <IssueStatusBadge status={issue.status} />
        <SeverityBadge severity={issue.severity} />
        <Badge tone="neutral">{areaLabel(issue.area)}</Badge>
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
