'use client';

/**
 * Models tab（模型库配置 + 列表 + 测试/启用/编辑/删除）。
 *
 * 从 app/model-eval/page.tsx 抽出的 145 行组件，包含：
 * - 模型统计 Surface（模型数 / 启用数 / 可调用数）
 * - 添加/编辑按钮触发 ModelEditForm 模态
 * - 模型卡片列表（Provider / 路由组 / 模型族 / 渠道 / 性能 / 费用 / 缓存命中）
 * - 内联测试按钮（handleTest 调用 modelsApi.test）
 * - 启用/编辑/删除 Toolbar
 *
 * 状态：editing（正在编辑的模型）/ testing（正在测试的 id）/
 * testResult（每个模型的最近测试结果）/ showAdd（显示添加表单）。
 *
 * ModelEditForm 以 AdminModal 弹窗承载，独立在 ModelEditForm.tsx，ModelsTab 通过
 * showAdd / editing 状态控制其显示；添加保存成功后自动对该模型触发一次连接测试。
 */

import React, { useState } from 'react';
import {
  KeyRound,
  Plus,
  Power,
  Settings2,
  Trash2,
} from 'lucide-react';
import { Button, Panel, Toolbar, cx } from '@/components/ui';
import { EmptyState } from '@/components/StateView';
import { InfoCell, StatusPill, Surface } from './_components';
import { modelsApi } from '@/lib/api';
import type { LlmModelItem } from '@/lib/api';
import { formatPerMillion } from './_model-eval-utils';
import { ModelEditForm } from './ModelEditForm';

export function ModelsTab({ models, onRefresh }: { models: LlmModelItem[]; onRefresh: () => void }) {
  const [editing, setEditing] = useState<LlmModelItem | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<Record<number, { status: string; response?: string; error?: string; duration_ms: number }>>({});
  const [showAdd, setShowAdd] = useState(false);

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

  const handleToggle = async (m: LlmModelItem) => {
    await modelsApi.update(m.id, { enabled: !m.enabled });
    onRefresh();
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除该模型配置？')) return;
    await modelsApi.delete(id);
    onRefresh();
  };

  const enabledCount = models.filter((m) => m.enabled).length;
  const keyedCount = models.filter((m) => m.api_key_set || !m.api_base).length;

  return (
    <div className="flex flex-col gap-3.5">
      <Surface title="模型配置" icon={Settings2} hint={`${models.length} 个模型 · ${enabledCount} 个启用 · ${keyedCount} 个可调用`}>
        <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
          <div className="text-[13px] leading-7 text-gray-500">
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
            onRefresh();
            if (saved && createdId) void handleTest(createdId);
          }}
        />
      )}
      {editing && (
        <ModelEditForm
          model={editing}
          onClose={() => {
            setEditing(null);
            onRefresh();
          }}
        />
      )}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {models.map((m) => (
          <Panel
            key={m.id}
            className={cx(
              'flex flex-col gap-3.5 p-4.5 transition',
              !m.enabled && 'opacity-60',
              m.enabled && m.routing_priority <= 10 && 'border-primary-border shadow-[0_12px_28px_rgba(255,107,53,0.08)]',
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  <StatusPill tone="neutral">#{m.routing_priority}</StatusPill>
                  {!m.enabled && <StatusPill>已禁用</StatusPill>}
                  {!m.api_key_set && m.api_base && <StatusPill tone="amber"><KeyRound size={11} />缺 Key</StatusPill>}
                </div>
                <div className="text-base font-black leading-5 text-gray-900">{m.name}</div>
                <div className="mt-1 truncate font-mono text-[11px] text-gray-400">{m.model_id}</div>
                {m.resolved_model !== m.model_id && (
                  <div className="mt-1 truncate font-mono text-[11px] text-primary">
                    实际请求 {m.resolved_model}
                  </div>
                )}
              </div>
              <StatusPill tone={m.enabled ? 'teal' : 'neutral'}>
                <Power size={11} />
                {m.enabled ? '启用' : '停用'}
              </StatusPill>
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <InfoCell label="Provider" value={m.provider} />
              <InfoCell label="路由组" value={m.routing_group || 'default'} />
              <InfoCell label="模型族" value={m.model_family || '-'} muted={!m.model_family} />
              <InfoCell label="渠道" value={m.channel_name || '-'} muted={!m.channel_name} />
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <InfoCell label="稳定度" value={m.temperature} />
              <InfoCell label="输出长度" value={m.max_tokens} />
              <InfoCell label="请求/分" value={m.requests_per_minute} />
              <InfoCell label="冷却" value={`${m.cooldown_seconds}s`} />
            </div>

            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <InfoCell label="输入未命中" value={formatPerMillion(m.cost_per_1m_input)} muted={m.cost_per_1m_input === null || m.cost_per_1m_input === undefined} />
              <InfoCell label="输出单价" value={formatPerMillion(m.cost_per_1m_output)} muted={m.cost_per_1m_output === null || m.cost_per_1m_output === undefined} />
            </div>

            {m.cost_per_1m_input_cache_hit !== null && m.cost_per_1m_input_cache_hit !== undefined && (
              <div className="flex items-center justify-between gap-3 rounded-xs border border-teal-border bg-teal-light px-2.5 py-2 text-[11px]">
                <span className="font-black text-gray-500">输入缓存命中</span>
                <span className="font-mono font-black text-teal">{formatPerMillion(m.cost_per_1m_input_cache_hit)}</span>
              </div>
            )}

            {m.description && <div className="text-xs leading-5 text-gray-500">{m.description}</div>}

            {testResult[m.id] && (
              <div
                className={cx(
                  'truncate rounded-xs border px-2.5 py-2 text-[11px]',
                  testResult[m.id].status === 'success'
                    ? 'border-teal-border bg-teal-light text-teal'
                    : 'border-red-light bg-red-light text-red',
                )}
              >
                {testResult[m.id].status === 'success'
                  ? `${testResult[m.id].duration_ms}ms: ${(testResult[m.id].response || '').slice(0, 40)}...`
                  : `失败: ${(testResult[m.id].error || '').slice(0, 30)}`}
              </div>
            )}

            <Toolbar className="border-t border-gray-100 pt-3">
              <Button type="button" variant="secondary" onClick={() => handleToggle(m)}>{m.enabled ? '禁用' : '启用'}</Button>
              <Button type="button" variant="secondary" onClick={() => handleTest(m.id)} disabled={testing === m.id} className="text-primary">
                {testing === m.id ? '测试中...' : '测试'}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setEditing(m)}>编辑</Button>
              <Button type="button" variant="danger" onClick={() => handleDelete(m.id)}>
                <Trash2 size={12} strokeWidth={2.2} />
                删除
              </Button>
            </Toolbar>
          </Panel>
        ))}
      </div>

      {models.length === 0 && (
        <Surface title="空模型库" icon={Settings2}>
          <EmptyState panel={false} minHeight="220px" title="还没有配置任何模型，点击“添加模型”开始" />
        </Surface>
      )}
    </div>
  );
}