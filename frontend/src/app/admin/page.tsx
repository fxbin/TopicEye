'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import {
  Activity,
  BarChart3,
  BookOpen,
  BrainCircuit,
  ChevronRight,
  GitMerge,
  Inbox,
  LayoutDashboard,
  MessageSquareWarning,
  Newspaper,
  RadioTower,
  RefreshCw,
  Rocket,
  ScrollText,
  Send,
  Settings,
  ShieldCheck,
  TriangleAlert,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { Panel, cx } from '@/components/ui';
import { AdminPageShell, AdminPageHeader } from '@/components/admin-ui';
import { AdminBlockSkeleton } from '@/components/admin';
import { useFetch } from '@/hooks/useFetch';
import { sourcesApi, statsApi, statsJobsApi, contentsApi, contentEventsAdminApi, productFeedbackApi } from '@/lib/api';
import type { BackendSource } from '@/components/SourceRow';
import type { IssueFeedbackItem } from '@/types/product-feedback';

/* ─── 概览分诊台（#125 v2，圆桌 r2-s1/s2 定稿）──
 *
 * 第一屏回答两个问题：「今天有没有异常」「去哪处理」。
 * 四格：信源健康 / 任务积压 / 待处理 / 今日流水。
 * 语义判定=数量阈值 OR 时长（沈观 r2-s2）；红黄用语义通道，
 * 与品牌橙（导航/主操作）不互借。各格独立取数独立重试，
 * 单格挂了不拖垮整页。侧栏徽章未来与四格同源（本期未做）。
 */

type TriageTone = 'ok' | 'warn' | 'danger';

const TONE_BADGE: Record<TriageTone, { label: string; className: string }> = {
  ok: { label: '正常', className: 'border-teal-border bg-teal-light text-teal-text' },
  warn: { label: '注意', className: 'border-amber-border bg-amber-light text-amber' },
  danger: { label: '异常', className: 'border-red-light bg-red-light text-red' },
};

function formatAgeHours(iso: string): number {
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

function TriageCard({
  icon: Icon,
  title,
  tone,
  loading,
  error,
  onRetry,
  href,
  linkLabel,
  children,
}: {
  icon: LucideIcon;
  title: string;
  tone: TriageTone;
  loading: boolean;
  error?: string | null;
  onRetry: () => void;
  href: string;
  linkLabel: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const badge = TONE_BADGE[tone];
  return (
    <Panel className="flex min-w-[280px] flex-col p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-ink-500">
          <Icon size={14} strokeWidth={2} aria-hidden="true" />
          {title}
        </div>
        <span className={cx('rounded-full border px-2 py-0.5 text-[10px] font-bold', badge.className)}>
          {badge.label}
        </span>
      </div>
      <div className="min-h-[72px] flex-1">
        {loading ? (
          <AdminBlockSkeleton lines={2} className="p-0" />
        ) : error ? (
          <div className="flex h-full flex-col justify-center">
            <p className="text-xs leading-5 text-ink-500">{error}</p>
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 inline-flex w-fit items-center gap-1 rounded-xs border border-ink-200 bg-white px-2 py-1 text-[11px] font-medium text-ink-700 transition hover:border-ink-300"
            >
              <RefreshCw size={11} strokeWidth={2} aria-hidden="true" />
              重试
            </button>
          </div>
        ) : (
          children
        )}
      </div>
      <button
        type="button"
        onClick={() => router.push(href)}
        className="mt-3 inline-flex w-fit items-center gap-0.5 text-xs font-medium text-primary-text transition hover:underline"
      >
        {linkLabel}
        <ChevronRight size={12} strokeWidth={2} aria-hidden="true" />
      </button>
    </Panel>
  );
}

function MetricValue({ tone, children }: { tone: TriageTone; children: React.ReactNode }) {
  return (
      <span
        className={cx(
          'font-mono text-2xl font-semibold tabular-nums',
          tone === 'danger' && 'text-red',
          tone === 'warn' && 'text-amber',
          tone === 'ok' && 'text-ink-900',
        )}
      >
      {children}
    </span>
  );
}

/* ─── 四格取数与判定 ─── */

function SourceHealthCard() {
  const { data, loading, error, refetch } = useFetch<{ items: BackendSource[]; total: number }>(
    async () => {
      // 分诊只需要全量信源的状态分布；后端上限 page_size=100，
      // 信源量级 ~24 远小于上限（超 100 时以 total 提示、计数按前 100 近似）
      const res = await sourcesApi.list({ page: 1, page_size: 100 });
      return { items: (res?.items || []) as BackendSource[], total: res?.total ?? 0 };
    },
    [],
  );

  const enabled = data?.items.filter((s) => s.enabled) ?? [];
  const errorCount = enabled.filter((s) => s.status === 'error').length;
  const noUpdate24h = enabled.filter((s) => {
    if (!s.last_sync_at) return true;
    return Date.now() - new Date(s.last_sync_at).getTime() > 24 * 3_600_000;
  }).length;
  const tone: TriageTone = errorCount > 0 ? 'danger' : noUpdate24h > 0 ? 'warn' : 'ok';

  return (
    <TriageCard
      icon={RadioTower}
      title="信源健康"
      tone={tone}
      loading={loading}
      error={error}
      onRetry={() => void refetch()}
      href="/admin/sources?view=list"
      linkLabel="去信源管理"
    >
      <div className="flex items-baseline gap-2">
        <MetricValue tone={tone}>{errorCount > 0 ? errorCount : noUpdate24h > 0 ? noUpdate24h : 0}</MetricValue>
        <span className="text-xs text-ink-500">
          {errorCount > 0 ? '个信源抓取报错' : noUpdate24h > 0 ? '个信源 24h 无更新' : '全部正常'}
        </span>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-ink-500">
        启用 {enabled.length} / 共 {data?.total ?? '-'} 个
        {noUpdate24h > 0 && errorCount > 0 && `，另有 ${noUpdate24h} 个 24h 无更新`}
      </p>
    </TriageCard>
  );
}

function JobsCard() {
  // initialLoading 用默认 true：与其余三格一致，首帧骨架屏，
  // 不闪「0 失败·正常」的瞬时错误状态（复审 nonblocking）
  const { data, loading, error, refetch } = useFetch(
    () => statsJobsApi.get(1, undefined),
    [],
  );
  const totals = data?.totals;
  const failed = totals?.failed_count ?? 0;
  const timeout = totals?.timeout_count ?? 0;
  const totalRuns = totals?.total_runs ?? 0;
  const tone: TriageTone = failed > 0 ? 'danger' : timeout > 0 ? 'warn' : 'ok';

  return (
    <TriageCard
      icon={Activity}
      title="任务积压（今日）"
      tone={tone}
      loading={loading}
      error={error}
      onRetry={() => void refetch()}
      href="/admin/jobs"
      linkLabel="去任务监控"
    >
      <div className="flex items-baseline gap-2">
        <MetricValue tone={tone}>{failed + timeout}</MetricValue>
        <span className="text-xs text-ink-500">
          {failed + timeout > 0 ? `次失败/超时（失败 ${failed}·超时 ${timeout}）` : '无失败记录'}
        </span>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-ink-500">
        今日共 {totalRuns.toLocaleString()} 次运行
        {totals && totalRuns > 0 && `，成功率 ${((totals.success_count / totalRuns) * 100).toFixed(1)}%`}
      </p>
    </TriageCard>
  );
}

function PendingCard() {
  const { data, loading, error, refetch } = useFetch(
    async () => {
      // 反馈量低（个位到百级），一页拉全算「最老未处理时长」；超页则只报数量
      const [events, issues] = await Promise.all([
        contentEventsAdminApi.listReviews({ page: 1, page_size: 1, review_status: 'pending' }),
        productFeedbackApi.listIssues({ status: 'open', limit: 200 }),
      ]);
      const items = (issues?.items || []) as IssueFeedbackItem[];
      const oldestHours =
        items.length > 0 && items.length >= (issues?.total ?? items.length)
          ? Math.max(...items.map((it) => formatAgeHours(it.created_at)))
          : null;
      return {
        pendingEvents: events?.total ?? 0,
        openFeedback: issues?.total ?? 0,
        oldestHours,
      };
    },
    [],
  );

  const { pendingEvents = 0, openFeedback = 0, oldestHours = null } = data ?? {};
  const tone: TriageTone =
    oldestHours != null && oldestHours > 48 ? 'danger' : pendingEvents > 0 || openFeedback > 0 ? 'warn' : 'ok';

  return (
    <TriageCard
      icon={Inbox}
      title="待处理"
      tone={tone}
      loading={loading}
      error={error}
      onRetry={() => void refetch()}
      href={pendingEvents > 0 ? '/admin/content-events' : '/admin/feedback'}
      linkLabel={pendingEvents > 0 ? '去事件治理' : '去反馈工作台'}
    >
      <div className="flex items-baseline gap-2">
        <MetricValue tone={tone}>{pendingEvents + openFeedback}</MetricValue>
        <span className="text-xs text-ink-500">项待处理（事件 {pendingEvents}·反馈 {openFeedback}）</span>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-ink-500">
        {openFeedback > 0
          ? oldestHours != null
            ? `最老反馈未处理 ${oldestHours < 24 ? `${Math.round(oldestHours)} 小时` : `${Math.round(oldestHours / 24)} 天`}`
            : '反馈较多，最老时长需到工作台查看'
          : '没有开放中的反馈'}
      </p>
    </TriageCard>
  );
}

function FlowCard() {
  // 口径：今日新增来自 statsApi 概览（窗口数），但「内容池总量」必须用
  // contents 列表的 total——getOverview(days) 的 total/curated 都是按窗口
  // 过滤的计数（复审判定的 blocking：不能把 24h 窗口数标成池总量）。
  const { data, loading, error, refetch } = useFetch(
    async () => {
      const [overview, contents] = await Promise.all([
        statsApi.getOverview(1),
        contentsApi.list({ page: 1, page_size: 1, admin_view: true }),
      ]);
      return {
        todayNew: overview?.today_new ?? 0,
        poolTotal: contents?.total ?? 0,
      };
    },
    [],
  );

  return (
    <TriageCard
      icon={Newspaper}
      title="今日流水"
      tone="ok"
      loading={loading}
      error={error}
      onRetry={() => void refetch()}
      href="/admin/contents"
      linkLabel="去内容管理"
    >
      <div className="flex items-baseline gap-2">
        <MetricValue tone="ok">{data?.todayNew ?? '-'}</MetricValue>
        <span className="text-xs text-ink-500">条今日新增</span>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-ink-500">
        内容池共 {(data?.poolTotal ?? 0).toLocaleString()} 条
      </p>
    </TriageCard>
  );
}

/* ─── 功能入口（保留原快捷卡，作为二级导航）── */

interface AdminDashboardCard {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  description: string;
}

const DASHBOARD_CARDS: AdminDashboardCard[] = [
  { id: 'sources', label: '信源管理', href: '/admin/sources', icon: RadioTower, description: '管理系统公共信源、采集频率与同步状态' },
  { id: 'contents', label: '内容管理', href: '/admin/contents', icon: Newspaper, description: '查看与维护内容池、原文快照与增强状态' },
  { id: 'content-events', label: '事件治理', href: '/admin/content-events', icon: GitMerge, description: '审核同事件消息关系，影子验证并控制归一化写入' },
  { id: 'users', label: '用户管理', href: '/admin/users', icon: Users, description: '管理用户角色、套餐、封禁与密码重置' },
  { id: 'model-eval', label: 'AI 引擎', href: '/admin/model-eval', icon: BrainCircuit, description: '配置与评测 LLM 模型、查看用量与效果' },
  { id: 'mother-topics', label: '母题库', href: '/admin/mother-topics', icon: BookOpen, description: '维护系统级母题模板库，用户可 fork 后个性化配置' },
  { id: 'updates', label: '发版记录', href: '/admin/updates', icon: Rocket, description: '管理版本发布记录与路线图' },
  { id: 'prompts', label: 'Prompt 管理', href: '/admin/prompts', icon: ScrollText, description: '查看系统 Prompt 模板、调用频次与成本统计' },
  { id: 'scoring-dashboard', label: '评分看板', href: '/admin/scoring-dashboard', icon: BarChart3, description: '推荐质量评估、用户反馈分布与个性化向量统计' },
  { id: 'evidence', label: '可信线索', href: '/admin/evidence', icon: ShieldCheck, description: '跨源证据标记统计与效果验证（交互率对比）' },
  { id: 'feedback', label: '反馈工作台', href: '/admin/feedback', icon: MessageSquareWarning, description: '查看与处理用户反馈、追踪修复状态' },
  { id: 'webhook-logs', label: 'Webhook 日志', href: '/admin/webhook-logs', icon: Send, description: '查看 Webhook 推送记录、状态码、耗时与错误详情' },
  { id: 'monitor', label: '任务监控', href: '/admin/jobs', icon: Activity, description: '抓取/调度任务运行统计与失败明细' },
  { id: 'settings', label: '系统设置', href: '/admin/settings', icon: Settings, description: '邮件服务、第三方登录与通知推送配置' },
];

export default function AdminDashboardPage() {
  const router = useRouter();

  return (
    <AdminPageShell maxWidth={1200}>
      <AdminPageHeader
        title="管理后台概览"
        icon={LayoutDashboard}
        description="第一屏回答：今天有没有异常、去哪处理。各格独立取数，单格失败可就地重试。"
      />

      {/* 分诊台四格：2×2，容器窄于 640 折单列（圆桌规格 gap16/最小宽280） */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <SourceHealthCard />
        <JobsCard />
        <PendingCard />
        <FlowCard />
      </div>

      {/* 功能入口 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {DASHBOARD_CARDS.map((card) => {
          const Icon = card.icon;
          return (
            <button
              key={card.id}
              type="button"
              onClick={() => router.push(card.href)}
              className="group text-left"
            >
              <Panel className="h-full p-4 transition hover:border-primary-border hover:shadow-[0_4px_16px_rgba(255,107,53,0.08)]">
                <div className="mb-2.5 flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-sm bg-ink-100 text-ink-700 transition group-hover:bg-primary-light group-hover:text-primary-text">
                    <Icon size={18} strokeWidth={2} />
                  </div>
                  <span className="text-sm font-semibold text-ink-900">{card.label}</span>
                </div>
                <p className="text-xs leading-5 text-ink-500">{card.description}</p>
              </Panel>
            </button>
          );
        })}
      </div>

      <p className="flex items-center gap-1.5 text-[11px] text-ink-500">
        <TriangleAlert size={11} strokeWidth={2} aria-hidden="true" />
        四格阈值：信源报错即红、24h 无更新为黄；任务失败红/超时黄；反馈超 48h 未处理红。
      </p>
    </AdminPageShell>
  );
}
