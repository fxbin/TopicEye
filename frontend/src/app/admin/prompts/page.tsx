'use client';

import React, { useState } from 'react';
import { FileCode2, Hash, Loader2, RefreshCw, ScrollText } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel } from '@/components/ui';
import { AdminPageShell, AdminPageHeader, AdminNoticeBanner, AdminModal } from '@/components/admin-ui';
import { LoadingState, ErrorState } from '@/components/StateView';
import { adminPromptsApi, type PromptAttemptStats } from '@/lib/api';
import { useFetch } from '@/hooks/useFetch';
import { formatDateTime } from '@/lib/datetime';
import { EDITION_LABELS } from '@/lib/edition-naming';

const LABELS: Record<string, string> = {
  content_analysis: '内容分析', classification: '内容分类', content_prescreen: '内容预筛',
  content_enrichment: '内容增强', creation_plan: '快速创作', creation_explore: '创作探索',
  creation_focus: '创作聚焦', creation_converge: '创作收敛', daily_report: EDITION_LABELS.daily_neutral,
  weekly_digest: EDITION_LABELS.weekly, monthly_digest: EDITION_LABELS.monthly, relation_discovery: '关系发现',
  topic_clustering: '话题命名', angle_recommend: '角度推荐', event_angles: '事件切面',
  mother_topic_keywords: '母题关键词', model_test: '模型连通测试',
};

export default function PromptsAdminPage() {
  const { currentUser, authLoading } = useAppContext();
  const [sceneFilter, setSceneFilter] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { data, loading, error, refetch } = useFetch(() => adminPromptsApi.list(), [], {
    enabled: !authLoading && currentUser?.role === 'admin',
  });
  const { data: detailResponse, loading: detailLoading, error: detailError, refetch: fetchDetail } = useFetch(
    async () => ({ id: selectedId, detail: await adminPromptsApi.detail(selectedId!) }),
    [selectedId], { enabled: selectedId !== null, initialLoading: false },
  );
  const detail = detailResponse?.id === selectedId ? detailResponse.detail : null;
  const scenes = (data?.scenes ?? []).filter(scene => !sceneFilter || scene.scene === sceneFilter);

  if (authLoading) return <LoadingState label="正在检查管理权限…" />;
  if (currentUser?.role !== 'admin') return <AdminPageShell><AdminNoticeBanner tone="red">需要管理员权限</AdminNoticeBanner></AdminPageShell>;

  return <AdminPageShell>
    <AdminPageHeader title="提示词目录与调用" icon={ScrollText}
      description="模板由代码维护；数据库保存目录副本。请求统计按业务场景汇总一次。"
      actions={<Button variant="secondary" disabled={loading} onClick={() => void refetch()}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />刷新</Button>} />
    <Panel className="space-y-2 p-4 text-sm leading-6 text-ink-500">
      <p>近 7 天统计包含请求成功和失败，覆盖该场景的所有模板版本。系统模板与用户模板常在同一次请求中使用，不能把模板数当作调用数。</p>
      <p className="text-xs">旧日志未记录模板组合、版本归因、独立业务请求或响应缓存命中，因此重试次数、缓存命中和单版模板用量暂不可归因。请求成功也不等于业务结果通过校验。</p>
    </Panel>
    {data && data.total < data.catalog_expected && <AdminNoticeBanner tone="amber">目录尚未完整同步：已登记 {data.total} / {data.catalog_expected} 份模板。服务重启后会从代码同步，缺失模板不代表没有实际调用。</AdminNoticeBanner>}
    <div className="flex flex-wrap items-center gap-3">
      <label htmlFor="prompt-scene" className="text-sm font-medium">业务场景</label>
      <select id="prompt-scene" value={sceneFilter} onChange={event => setSceneFilter(event.target.value)} className="min-h-10 max-w-full rounded-sm border border-ink-200 bg-white px-3 text-sm">
        <option value="">全部场景</option>
        {(data?.scenes ?? []).map(scene => <option key={scene.scene} value={scene.scene}>{LABELS[scene.scene] || scene.scene}</option>)}
      </select>
      <span className="text-xs text-ink-500">已同步 {data?.total ?? '—'} 份代码模板</span>
    </div>
    {error && <ErrorState error={error} onRetry={() => void refetch()} panel />}
    {loading && !data ? <LoadingState label="加载提示词目录…" /> : scenes.length ? <div className="space-y-4">
      {scenes.map(scene => <Panel key={scene.scene} className="overflow-hidden">
        <div className="space-y-4 border-b border-ink-200 bg-ink-100/50 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><h2 className="font-semibold text-ink-900">{LABELS[scene.scene] || scene.scene}</h2><p className="mt-1 break-all font-mono text-xs text-ink-500">{scene.scene} · {scene.template_count} 份模板</p></div>
            {!scene.template_count && <Badge tone="amber">动态输入或未登记模板</Badge>}
          </div>
          <AttemptStats stats={scene.stats_7d} window="7天" />
        </div>
        <div className="divide-y divide-ink-200">
          {(data?.items ?? []).filter(item => item.scene === scene.scene).map(item => <button type="button" key={item.id} onClick={() => setSelectedId(item.id)} aria-label={`查看 ${item.name} 的提示词详情`} className="block w-full space-y-2 p-4 text-left transition hover:bg-ink-100/50 focus-visible:outline-primary">
            <div className="flex flex-wrap items-center gap-2"><span className="break-all font-mono text-sm font-semibold">{item.name}</span><Badge tone="neutral">代码模板</Badge></div>
            <p className="text-sm text-ink-500">{item.description}</p>
            <div className="flex flex-wrap items-center gap-3 text-xs text-ink-500"><span className="flex min-w-0 items-center gap-1"><FileCode2 size={12} className="shrink-0" /><span className="break-all">{item.source_file.split(':').pop()}</span></span><span className="font-mono">版本 {item.version_hash}</span></div>
          </button>)}
          {!scene.template_count && <p className="p-4 text-sm leading-6 text-ink-500">调用记录仍计入场景总量。该场景可能来自自定义评测或尚未登记的业务模板，不能据此推断具体模板版本。</p>}
        </div>
      </Panel>)}
    </div> : !error && <Panel className="p-6 text-sm text-ink-500">当前没有匹配的场景或已同步模板。</Panel>}
    {selectedId !== null && <AdminModal title="代码模板详情" onClose={() => setSelectedId(null)} maxWidth={840}>
      {detailLoading || (!detail && !detailError) ? <div role="status" className="flex items-center justify-center gap-2 p-8"><Loader2 size={18} className="animate-spin" />正在读取模板…</div> : detail ? <div className="space-y-5">
        <div className="space-y-2"><h2 className="break-all font-mono font-semibold">{detail.name}</h2><p className="text-sm text-ink-500">{detail.description}</p><p className="break-all text-xs text-ink-500">{detail.source_file}</p><div className="flex flex-wrap items-center gap-2 text-xs text-ink-500"><Hash size={12} /><span className="font-mono">{detail.version_hash.slice(0, 12)}</span>{detail.updated_at && <span>目录更新：{formatDateTime(detail.updated_at)}</span>}</div></div>
        <div className="space-y-3 rounded-sm border border-ink-200 p-4"><h3 className="text-sm font-semibold">所属场景近 30 天 · 所有版本</h3><AttemptStats stats={detail.stats_30d} window="30天" /><p className="text-xs leading-6 text-ink-500">这些统计属于整个 {LABELS[detail.scene] || detail.scene} 场景，不是当前模板或当前哈希的专属用量。</p></div>
        {!!detail.daily_trend.length && <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="mb-2 text-left font-medium">场景请求趋势（所有版本）</caption><thead><tr><th className="py-2">日期</th><th>尝试</th><th>成功</th><th>失败</th></tr></thead><tbody>{detail.daily_trend.map(day => <tr key={day.date} className="border-t border-ink-200"><td className="py-2 font-mono">{day.date}</td><td>{day.call_count}</td><td>{day.success_count}</td><td>{day.failed_count}</td></tr>)}</tbody></table></div>}
        <section><h3 className="mb-2 text-sm font-semibold">当前代码模板</h3><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-ink-900 p-4 text-xs leading-6 text-ink-100">{detail.full_content}</pre></section>
      </div> : <div role="alert" className="p-6 text-sm">{detailError || '模板读取失败'}<Button variant="secondary" onClick={() => void fetchDetail()}>重试详情</Button></div>}
    </AdminModal>}
  </AdminPageShell>;
}

function AttemptStats({ stats, window }: { stats: PromptAttemptStats; window: string }) {
  const entries = [[`${window}请求尝试`, stats.call_count], ['请求成功', stats.success_count], ['请求失败', stats.failed_count], ['记录成本', `$${stats.total_cost.toFixed(4)}`]];
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{entries.map(([label, value]) => <div key={label}><div className="font-mono text-lg font-semibold tabular-nums text-ink-900">{value}</div><div className="mt-1 text-xs text-ink-500">{label}</div></div>)}{stats.other_count > 0 && <p className="col-span-full text-xs text-ink-500">另有 {stats.other_count} 条其它状态记录</p>}</div>;
}
