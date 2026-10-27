'use client';

/**
 * Models tab（模型库配置 + 列表 + 测试/启用/编辑/删除）。
 *
 * 从 app/model-eval/page.tsx 抽出的组件，包含：
 * - 模型统计 Surface（模型数 / 启用数 / 可调用数）
 * - 添加/编辑按钮触发 ModelEditForm 模态
 * - 模型卡片列表（Provider / 路由组 / 模型族 / 渠道 / 运行参数 / 费用）
 * - 内联测试按钮（handleTest 调用 modelsApi.test）
 * - 启用/编辑/删除 Toolbar
 *
 * 视觉层级口径（延续 v2 换壳的 ink 三档与 Badge 状态语言）：
 * - 卡片头部只留一个主角（模型名）；路由优先级降为名字旁的 mono 次要信息，
 *   状态徽章收敛为 启用/停用 + 缺 Key（原头部「已禁用」与右上徽章语义重复）
 * - 身份信息（Provider/路由组/模型族/渠道）保留格子；运行参数与单价降为
 *   行内轻量文本——此前 11 个等权格子把配置项全铺成同一层，扫读找不到重点
 * - 单价未填或为 0 显示「未设」（后端会按目录价兜底估算），不再展示
 *   ¥0.0000/百万 的零值噪音；缓存命中价并入同一行
 * - 首选路由高亮改为精确判断：default 组启用模型中优先级最小者，
 *   主色边框 + 「首选路由」徽章（原 priority<=10 阴影含义模糊）
 * - 停用卡片改浅灰底表达状态，不再整体 opacity（文字可读性优先）
 * - 删除走 AdminModal 二次确认（对齐 sources 页收口模式，替代原生 confirm）
 *
 * 状态：editing（正在编辑的模型）/ testing（正在测试的 id）/
 * testResult（每个模型的最近测试结果）/ showAdd（显示添加表单）/
 * confirmDelete（待二次确认删除的模型）。
 *
 * ModelEditForm 以 AdminModal 弹窗承载，独立在 ModelEditForm.tsx，ModelsTab 通过
 * showAdd / editing 状态控制其显示；添加保存成功后自动对该模型触发一次连接测试。
 */

import React, { useRef, useState } from 'react';
import {
  CheckCircle2,
  KeyRound,
  Plus,
  Power,
  Settings2,
  Trash2,
  XCircle,
} from 'lucide-react';
import { AdminModal, AdminModalFooter } from '@/components/admin-ui';
import { Button, Panel, Toolbar, cx } from '@/components/ui';
import { EmptyState } from '@/components/StateView';
import { InfoCell, StatusPill, Surface } from './_components';
import { modelsApi } from '@/lib/api';
import type { LlmModelItem } from '@/lib/api';
import { formatPerMillion } from './_model-eval-utils';
import { ModelEditForm } from './ModelEditForm';

/** 单价视为未设置的口径：null/undefined（没填）与 0（历史种子数据默认值）都按未设展示，费用估算由后端目录价兜底 */
function priceUnset(value: number | null | undefined): boolean {
  return value === null || value === undefined || value === 0;
}

/** 行内轻量参数项：label + mono 值，无格子边框，用于低频参考信息 */
function InlineParam({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-ink-500">{label}</span>
      <span className="font-mono font-black text-ink-700">{value}</span>
    </span>
  );
}

/** 行内单价项：未设时灰掉，设了价的用 mono 突出 */
function InlinePrice({ label, value }: { label: string; value: number | null | undefined }) {
  const unset = priceUnset(value);
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-ink-500">{label}</span>
      <span className={cx('font-mono font-black', unset ? 'text-ink-500' : 'text-ink-900')}>
        {unset ? '未设' : formatPerMillion(value)}
      </span>
    </span>
  );
}

export function ModelsTab({ models, onRefresh }: { models: LlmModelItem[]; onRefresh: () => Promise<void> }) {
  const [editing, setEditing] = useState<LlmModelItem | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<Record<number, { status: string; response?: string; note?: string; error?: string; duration_ms: number }>>({});
  const [showAdd, setShowAdd] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<LlmModelItem | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<number, string>>({});
  const [actingIds, setActingIds] = useState<Set<number>>(new Set());
  const pendingActions = useRef(new Set<number>());

  const handleTest = async (id: number) => {
    setTesting(id);
    try {
      const res = await modelsApi.test(id);
      setTestResult((prev) => ({ ...prev, [id]: res }));
    } catch (e: unknown) {
      setTestResult((prev) => ({ ...prev, [id]: { status: 'failed', error: String(e), duration_ms: 0 } }));
    }
    setTesting(null);
  };

  const runAction = async (id: number, action: () => Promise<unknown>) => {
    if (pendingActions.current.has(id)) return;
    pendingActions.current.add(id);
    setActingIds(new Set(pendingActions.current));
    setActionErrors((current) => { const next = { ...current }; delete next[id]; return next; });
    try {
      await action();
      await onRefresh();
    } catch (error) {
      setActionErrors((current) => ({ ...current, [id]: error instanceof Error ? error.message : '操作失败，请重试' }));
    } finally {
      pendingActions.current.delete(id);
      setActingIds(new Set(pendingActions.current));
    }
  };

  const handleToggle = (m: LlmModelItem) => {
    void runAction(m.id, () => modelsApi.update(m.id, { enabled: !m.enabled }));
  };

  const handleConfirmDelete = () => {
    if (!confirmDelete) return;
    const target = confirmDelete;
    setConfirmDelete(null);
    void runAction(target.id, () => modelsApi.delete(target.id));
  };

  const enabledCount = models.filter((m) => m.enabled).length;
  const keyedCount = models.filter((m) => m.api_key_set || !m.api_base).length;
  // default 组的首选路由：与运行时选路口径一致（组内启用模型按优先级升序取最小）
  const defaultGroupFirst = [...models]
    .filter((m) => m.enabled && (m.routing_group || 'default') === 'default')
    .sort((a, b) => a.routing_priority - b.routing_priority || a.id - b.id)[0];

  return (
    <div className="flex flex-col gap-3.5">
      <Surface title="模型配置" icon={Settings2} hint={`${models.length} 个模型 · ${enabledCount} 个启用 · ${keyedCount} 个可调用`}>
        <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
          <div className="text-[13px] leading-7 text-ink-500">
            维护运行时路由链、渠道分组和可参与测评的候选模型。禁用模型不会参与自动任务和 A/B 测评。
          </div>
          <Button type="button" variant="primary" onClick={() => setShowAdd(true)} className="w-fit whitespace-nowrap">
            <Plus size={14} strokeWidth={2.2} />
            添加模型
          </Button>
        </div>
      </Surface>

      {showAdd && (
        <ModelEditForm
          onClose={(saved, createdId) => {
            setShowAdd(false);
            void onRefresh().catch(() => {}); // 页面显示刷新错误。
            if (saved && createdId) void handleTest(createdId);
          }}
        />
      )}
      {editing && (
        <ModelEditForm
          model={editing}
          onClose={() => {
            setEditing(null);
            void onRefresh().catch(() => {}); // 页面显示刷新错误。
          }}
        />
      )}

      <div className={cx('grid grid-cols-1 gap-3', models.length > 1 && 'xl:grid-cols-2')}>
        {models.map((m) => {
          const isPreferred = m.id === defaultGroupFirst?.id;
          return (
            <Panel
              key={m.id}
              className={cx(
                'flex flex-col gap-3 p-4.5 transition',
                !m.enabled && 'bg-ink-100/60',
                isPreferred && 'border-primary-border',
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className="text-base font-black leading-5 text-ink-900">{m.name}</span>
                    <span className="font-mono text-[11px] font-black text-ink-500">#{m.routing_priority}</span>
                  </div>
                  <div className="mt-1 truncate font-mono text-[11px] text-ink-500">{m.model_id}</div>
                  {m.resolved_model !== m.model_id && (
                    <div className="mt-1 truncate font-mono text-[11px] text-primary">
                      实际请求 {m.resolved_model}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  <StatusPill tone={m.enabled ? 'teal' : 'neutral'}>
                    <Power size={11} />
                    {m.enabled ? '启用' : '停用'}
                  </StatusPill>
                  {isPreferred && <StatusPill tone="primary">首选路由</StatusPill>}
                  {!m.api_key_set && m.api_base && <StatusPill tone="amber"><KeyRound size={11} />缺 Key</StatusPill>}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <InfoCell label="Provider" value={m.provider} />
                <InfoCell label="路由组" value={m.routing_group || 'default'} />
                <InfoCell label="模型族" value={m.model_family || '-'} muted={!m.model_family} />
                <InfoCell label="渠道" value={m.channel_name || '-'} muted={!m.channel_name} />
              </div>

              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] leading-4">
                <InlineParam label="稳定度" value={m.temperature} />
                <InlineParam label="输出长度" value={m.max_tokens} />
                <InlineParam label="请求/分" value={m.requests_per_minute} />
                <InlineParam label="冷却" value={`${m.cooldown_seconds}s`} />
              </div>

              <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-ink-100 pt-2.5 text-[11px] leading-4">
                <InlinePrice label="输入未命中" value={m.cost_per_1m_input} />
                <InlinePrice label="输出单价" value={m.cost_per_1m_output} />
                <InlinePrice label="缓存命中" value={m.cost_per_1m_input_cache_hit} />
              </div>

              {m.description && <div className="text-xs leading-5 text-ink-500">{m.description}</div>}

              {testResult[m.id] && (
                <div
                  className={cx(
                    'rounded-xs border px-2.5 py-2 text-[11px] leading-4',
                    testResult[m.id].status === 'success'
                      ? 'border-teal-border bg-teal-light text-teal'
                      : 'border-red-light bg-red-light text-red',
                  )}
                >
                  <div className="mb-1 flex items-center gap-1.5 font-black">
                    {testResult[m.id].status === 'success' ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                    {testResult[m.id].status === 'success' ? (
                      <>连接成功 <span className="font-mono">{testResult[m.id].duration_ms}ms</span></>
                    ) : (
                      '连接失败'
                    )}
                  </div>
                  <div className="whitespace-pre-line break-all font-mono">
                    {testResult[m.id].status === 'success'
                      ? (testResult[m.id].response || '').slice(0, 120)
                      : (testResult[m.id].error || '').slice(0, 300)}
                  </div>
                  {testResult[m.id].note && <div className="mt-1 text-ink-500">{testResult[m.id].note}</div>}
                </div>
              )}

              <Toolbar className="border-t border-ink-100 pt-3">
                <Button type="button" variant="primary" onClick={() => handleTest(m.id)} disabled={testing === m.id}>
                  {testing === m.id ? '测试中...' : '测试'}
                </Button>
                <Button type="button" variant="secondary" onClick={() => setEditing(m)} disabled={actingIds.has(m.id)}>编辑</Button>
                <Button type="button" variant="secondary" onClick={() => handleToggle(m)} disabled={actingIds.has(m.id)}>{actingIds.has(m.id) ? '处理中…' : m.enabled ? '禁用' : '启用'}</Button>
                <Button type="button" variant="ghost" onClick={() => setConfirmDelete(m)} disabled={actingIds.has(m.id)} className="ml-auto text-red hover:bg-red-light hover:text-red">
                  <Trash2 size={12} strokeWidth={2.2} />
                  删除
                </Button>
              </Toolbar>
              {actionErrors[m.id] && <p role="alert" className="text-xs font-bold leading-5 text-red">{actionErrors[m.id]}</p>}
            </Panel>
          );
        })}
      </div>

      {models.length === 0 && (
        <Surface title="空模型库" icon={Settings2}>
          <EmptyState panel={false} minHeight="220px" title="还没有配置任何模型，点击“添加模型”开始" />
        </Surface>
      )}

      {confirmDelete && (
        <AdminModal title="删除模型配置" onClose={() => setConfirmDelete(null)}>
          <p className="text-[13px] leading-6 text-ink-700">
            确定删除「{confirmDelete.name}」？删除后该模型立即退出路由与 A/B 测评，操作不可恢复。
          </p>
          <AdminModalFooter>
            <Button type="button" variant="secondary" onClick={() => setConfirmDelete(null)}>取消</Button>
            <Button type="button" variant="danger" onClick={handleConfirmDelete}>
              <Trash2 size={12} strokeWidth={2.2} />
              删除
            </Button>
          </AdminModalFooter>
        </AdminModal>
      )}
    </div>
  );
}
