'use client';

import React, { useMemo } from 'react';
import { Check, Gem, LockKeyhole, ShieldCheck, Sparkles, UserRound } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { plansApi } from '@/lib/api';
import { Badge, Panel, cx } from '@/components/ui';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import type { PlanCatalogResponse, PlanTier } from '@/types';

const LIMIT_LABELS: Record<string, string> = {
  daily_topic_view: '每日选题',
  favorites: '收藏容量',
  custom_sources: '自定义信源',
  creation_plans_per_day: 'AI 方案/日',
  team_members: '团队成员',
};

function formatLimit(value: unknown): string {
  if (value === -1) return '不限';
  if (value === 0) return '无';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value;
  return '-';
}

export default function PlansPage() {
  const { currentUser, authLoading } = useAppContext();
  const { data: catalog, loading, error, refetch } = useFetch<PlanCatalogResponse>(
    async () => {
      try {
        return await plansApi.list();
      } catch (err) {
        throw new Error(err instanceof Error ? err.message : '权益规划加载失败');
      }
    },
    [currentUser?.plan],
    { enabled: !authLoading },
  );

  const recommended = useMemo(() => catalog?.tiers.find((tier) => tier.recommended), [catalog]);
  const currentTier = useMemo(
    () => catalog?.current_tier || catalog?.tiers.find((tier) => tier.key === catalog.current_plan) || null,
    [catalog],
  );

  return (
    <div className="fade-in h-full overflow-y-auto px-6 py-6 lg:px-10 lg:py-8">
      <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="mb-3 inline-flex items-center gap-2 rounded-sm border border-primary-border bg-primary-light px-3 py-1.5 text-xs font-black text-primary">
            <Gem size={14} />
            功能权益
          </div>
          <h1 className="mb-1.5 text-[26px] font-black text-gray-900">功能边界与后续规划</h1>
          <p className="max-w-[760px] text-[13px] leading-6 text-gray-500">
            这里展示当前已经开放的访问边界，以及还没有正式上线的付费和团队能力。未标为当前可用的内容只作为路线图，不作为已交付承诺。
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:min-w-[560px]">
          {currentTier && (
            <Panel className="p-4">
              <div className="mb-1 flex items-center gap-2 text-xs font-black text-teal">
                <UserRound size={14} />
                当前账号权益
              </div>
              <div className="text-lg font-black text-gray-900">{currentTier.name}</div>
              <div className="mt-1 text-xs leading-5 text-gray-500">
                {currentUser ? `${currentUser.display_name || currentUser.email} · ${currentTier.highlight}` : '未登录时只展示公开访问边界'}
              </div>
            </Panel>
          )}
          {recommended && (
            <Panel className="p-4">
              <div className="mb-1 flex items-center gap-2 text-xs font-black text-primary">
                <Sparkles size={14} />
                当前建议主推
              </div>
              <div className="text-lg font-black text-gray-900">{recommended.name}</div>
              <div className="mt-1 text-xs leading-5 text-gray-500">{recommended.highlight}</div>
            </Panel>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4">
          <ErrorState error={error} onRetry={() => void refetch()} panel={false} />
        </div>
      )}

      {loading ? (
        <LoadingState label="加载中…" minHeight="200px" />
      ) : catalog && (
        <>
          <div className="mb-5 grid gap-3 lg:grid-cols-2">
            <AreaPanel title="当前访问边界" icon={<ShieldCheck size={17} />} items={catalog.free_area} tone="teal" />
            <AreaPanel title="付费与团队规划" icon={<LockKeyhole size={17} />} items={catalog.paid_area} tone="primary" />
          </div>

          <div className="grid gap-3 pb-10 xl:grid-cols-4">
            {catalog.tiers.map((tier) => (
              <PlanCard key={tier.key} tier={tier} current={tier.key === catalog.current_plan} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function AreaPanel({
  title,
  icon,
  items,
  tone,
}: {
  title: string;
  icon: React.ReactNode;
  items: string[];
  tone: 'primary' | 'teal';
}) {
  return (
    <Panel className="p-5">
      <div className={cx('mb-3 flex items-center gap-2 text-sm font-black', tone === 'primary' ? 'text-primary' : 'text-teal')}>
        {icon}
        {title}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {items.map((item) => (
          <div key={item} className="flex items-start gap-2 text-[13px] leading-6 text-gray-600">
            <Check size={14} className={cx('mt-1 shrink-0', tone === 'primary' ? 'text-primary' : 'text-teal')} />
            <span>{item}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function PlanCard({ tier, current }: { tier: PlanTier; current: boolean }) {
  return (
    <Panel className={cx(
      'relative flex min-h-[420px] flex-col p-5',
      tier.recommended && 'border-primary-border shadow-sm',
      current && 'border-teal-border shadow-sm',
    )}>
      {current && (
        <Badge tone="teal" className="absolute right-4 top-4 rounded-sm">
          当前
        </Badge>
      )}
      {tier.recommended && (
        <Badge tone="primary" className={cx('absolute rounded-sm', current ? 'right-16 top-4' : 'right-4 top-4')}>
          推荐
        </Badge>
      )}
      <div className="mb-3">
        <div className="text-sm font-black text-gray-900">{tier.name}</div>
        <div className="mt-1 font-mono text-2xl font-black text-gray-900">{tier.price_label}</div>
      </div>
      <div className="mb-3 min-h-12 text-[13px] leading-6 text-gray-500">{tier.positioning}</div>
      <div className="mb-4 rounded-sm border border-gray-100 bg-gray-50 px-3 py-2 text-xs font-bold leading-5 text-gray-600">
        {tier.highlight}
      </div>
      <div className="mb-4 grid gap-1.5">
        {tier.features.map((feature) => (
          <div key={feature} className="flex items-center gap-2 text-[13px] text-gray-700">
            <Check size={13} className="shrink-0 text-teal" />
            <span>{feature}</span>
          </div>
        ))}
      </div>
      <div className="mt-auto border-t border-gray-100 pt-4">
        <div className="mb-2 text-[11px] font-black text-gray-400">额度边界</div>
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(tier.limits).map(([key, value]) => (
            <div key={key} className="rounded-sm bg-gray-50 px-2 py-2">
              <div className="text-[10px] font-bold text-gray-400">{LIMIT_LABELS[key] || key}</div>
              <div className="font-mono text-sm font-black text-gray-900">{formatLimit(value)}</div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}
