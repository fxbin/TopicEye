'use client';

import React, { useId, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, ArrowRight, Settings } from 'lucide-react';
import { motherTopicsApi, type MotherTopic } from '@/lib/api';
import { Badge, Button, Panel, Toolbar, type Tone } from '@/components/ui';
import { AdminPageShell, AdminPageHeader } from '@/components/admin-ui';
import { FieldLabel } from '@/components/form';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';

/* ── helpers ── */

// 内容类型标签色：原为散落的 hex 手写色，现按色系就近映射到 Badge tone
// （「观点」原值 #8B5CF6 与项目 purple token 同值；「教程」原 sky 蓝无对应
// token，落 neutral 保持安静），未知类型一律回 neutral。
const CONTENT_TYPE_TONE: Record<string, Tone> = {
  '工具评测': 'primary',
  '方法论': 'teal',
  '观察': 'amber',
  '随笔': 'red',
  '教程': 'neutral',
  '观点': 'purple',
};

function TopicCard({
  topic,
  onSave,
  onDelete,
}: {
  topic: MotherTopic;
  onSave: (updated: Partial<MotherTopic>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: topic.name,
    description: topic.description || '',
    keywords: topic.keywords.join(', '),
    weight: topic.weight,
    content_type: topic.content_type || '',
    target_reader: topic.target_reader || '',
    is_active: topic.is_active,
    display_order: topic.display_order,
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const formId = useId();

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    const keywords = form.keywords.split(',').map(k => k.trim()).filter(Boolean);
    try {
      await onSave({
      name: form.name,
      description: form.description || undefined,
      keywords,
      weight: form.weight,
      content_type: form.content_type || undefined,
      target_reader: form.target_reader || undefined,
      is_active: form.is_active,
      display_order: form.display_order,
      });
      setEditing(false);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : '保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const handleActiveChange = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      if (topic.is_active) await onDelete(topic.id);
      else await onSave({ is_active: true });
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : '更新状态失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel className="mb-4 p-5">
      {/* card header */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <h3 className="m-0 text-base font-bold text-ink-900">{topic.name}</h3>
            {topic.content_type && (
              <Badge tone={CONTENT_TYPE_TONE[topic.content_type] ?? 'neutral'}>{topic.content_type}</Badge>
            )}
          </div>
          {topic.description && (
            <p className="m-0 mt-0.5 text-xs leading-5 text-ink-500">
              {topic.description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className="whitespace-nowrap text-xs tabular-nums text-ink-500">权重 {topic.weight}</span>
          {!topic.is_active && (
            <Badge tone="red" className="whitespace-nowrap rounded-sm px-2 py-0.5 text-xs">已停用</Badge>
          )}
        </div>
      </div>

      {editing ? (
        /* edit form */
        <div className="flex flex-col gap-3">
          <div>
            <FieldLabel htmlFor={`${formId}-name`}>名称</FieldLabel>
            <input
              id={`${formId}-name`}
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              className="w-full rounded-xs border border-ink-200 bg-white px-2.5 py-1.5 text-[13px] text-ink-900 outline-none focus:border-admin-accent"
            />
          </div>
          <div>
            <FieldLabel htmlFor={`${formId}-description`}>描述</FieldLabel>
            <input
              id={`${formId}-description`}
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              className="w-full rounded-xs border border-ink-200 bg-white px-2.5 py-1.5 text-[13px] text-ink-900 outline-none focus:border-admin-accent"
            />
          </div>
          <div>
            <FieldLabel htmlFor={`${formId}-keywords`}>关键词（逗号分隔）</FieldLabel>
            <textarea
              id={`${formId}-keywords`}
              value={form.keywords}
              onChange={e => setForm({ ...form, keywords: e.target.value })}
              rows={4}
              className="w-full resize-y rounded-xs border border-ink-200 bg-white px-2.5 py-1.5 font-mono text-xs text-ink-900 outline-none focus:border-admin-accent"
            />
            <div className="mt-1 text-[11px] tabular-nums text-ink-500">
              当前 {form.keywords.split(',').filter(k => k.trim()).length} 个关键词
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <div className="flex-1">
              <FieldLabel htmlFor={`${formId}-weight`}>权重乘数</FieldLabel>
              <input
                id={`${formId}-weight`}
                type="number"
                step="0.1"
                min="0.1"
                max="3"
                value={form.weight}
                onChange={e => setForm({ ...form, weight: parseFloat(e.target.value) })}
                className="w-full rounded-xs border border-ink-200 bg-white px-2.5 py-1.5 text-[13px] text-ink-900 outline-none focus:border-admin-accent"
              />
            </div>
            <div className="flex-1">
              <FieldLabel htmlFor={`${formId}-reader`}>目标读者</FieldLabel>
              <input
                id={`${formId}-reader`}
                value={form.target_reader}
                onChange={e => setForm({ ...form, target_reader: e.target.value })}
                className="w-full rounded-xs border border-ink-200 bg-white px-2.5 py-1.5 text-[13px] text-ink-900 outline-none focus:border-admin-accent"
              />
            </div>
          </div>
          <Toolbar className="gap-2">
            <Button
              type="button"
              onClick={handleSave}
              disabled={saving}
              variant="success"
              className="min-h-0 px-4 py-1.5 text-[13px] font-medium"
            >
              {saving ? '保存中...' : '保存'}
            </Button>
            <Button
              type="button"
              onClick={() => setEditing(false)}
              disabled={saving}
              variant="ghost"
              className="min-h-0 px-4 py-1.5 text-[13px] font-medium"
            >
              取消
            </Button>
          </Toolbar>
        </div>
      ) : (
        /* view mode */
        <>
          {/* keywords display */}
          <div className="mb-3">
            <div className="mb-1.5 text-xs font-semibold tabular-nums text-ink-700">
              关键词 ({topic.keywords.length})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {topic.keywords.slice(0, 20).map(kw => (
                <Badge key={kw} tone="neutral" className="rounded-full px-2.5 py-1 text-xs">{kw}</Badge>
              ))}
              {topic.keywords.length > 20 && (
                <span className="px-2 py-1 text-xs tabular-nums text-ink-500">
                  +{topic.keywords.length - 20} 更多
                </span>
              )}
            </div>
          </div>

          {/* target reader */}
          {topic.target_reader && (
            <div className="mb-3 text-xs text-ink-500">
              <b>目标读者:</b> {topic.target_reader}
            </div>
          )}

          {/* actions */}
          <Toolbar className="mt-3 border-t border-ink-100 pt-3">
            <Button
              type="button"
              onClick={() => { setSaveError(null); setEditing(true); setForm({ name: topic.name, description: topic.description || '', keywords: topic.keywords.join(', '), weight: topic.weight, content_type: topic.content_type || '', target_reader: topic.target_reader || '', is_active: topic.is_active, display_order: topic.display_order }); }}
              variant="primary"
              className="min-h-0 px-3.5 py-1.5 text-xs font-medium"
            >
              编辑
            </Button>
            {topic.is_active ? (
              <Button
                type="button"
                onClick={() => void handleActiveChange()}
                disabled={saving}
                variant="danger"
                className="min-h-0 px-3.5 py-1.5 text-xs font-medium"
              >
                停用
              </Button>
            ) : (
              <Button
                type="button"
                onClick={() => void handleActiveChange()}
                disabled={saving}
                variant="success"
                className="min-h-0 px-3.5 py-1.5 text-xs font-medium"
              >
                启用
              </Button>
            )}
          </Toolbar>
        </>
      )}
      {saveError && <p role="alert" className="mt-3 text-sm text-red-700">{saveError}</p>}
    </Panel>
  );
}

/* ── Main Page ── */

export default function MotherTopicsConfigPage() {
  const router = useRouter();
  const { data: topics, loading, error, refetch } = useFetch<MotherTopic[]>(
    async () => {
      const ts = await motherTopicsApi.list(false, 'all');
      return ts.sort((a, b) => a.display_order - b.display_order);
    },
    [],
  );

  const handleSave = async (id: number, updated: Partial<MotherTopic>) => {
    await motherTopicsApi.update(id, updated);
    await refetch();
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确认停用此母题？停用后相关推荐将不再出现。')) return;
    await motherTopicsApi.delete(id);
    await refetch();
  };

  return (
    <AdminPageShell maxWidth={860}>
      <AdminPageHeader
        title="系统母题模板库"
        icon={Settings}
        description="维护系统级母题模板，所有用户可见且只读。用户会 fork 一份副本到自己的母题进行个性化配置。"
        actions={
          <Button
            type="button"
            onClick={() => router.push('/my-topics')}
            variant="secondary"
            className="text-[13px] font-medium"
          >
            <ArrowLeft size={14} strokeWidth={2} />
            返回我的母题
          </Button>
        }
      />

      {/* Info box */}
      <Panel className="mb-6 border-teal-border bg-teal-light px-4 py-3 text-[13px] leading-6 text-teal">
        <b>打分规则:</b> 母题匹配分 × 权重 + 新鲜度加成 <ArrowRight size={13} strokeWidth={2} className="inline align-[-2px]" /> 最终得分<br/>
        <b>阈值:</b> 80+ 今日主选题 / 65-79 值得储备 / 50-64 观察池 / &lt;50 过滤
      </Panel>

      {error && (
        <div className="mb-4">
          <ErrorState error={error} onRetry={() => void refetch()} panel={false} />
        </div>
      )}

      {/* Topics */}
      {loading ? (
        <LoadingState label="加载中…" minHeight="160px" />
      ) : (
        <div>
          {(topics || []).map(topic => (
            <TopicCard
              key={topic.id}
              topic={topic}
              onSave={updated => handleSave(topic.id, updated)}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {/* Scoring explanation */}
      <Panel className="mt-8 bg-ink-100 p-4">
        <h3 className="mb-3 text-sm font-bold text-ink-700">打分公式详解</h3>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2">
          {[
            ['母题匹配', '0.0~1.0（匹配1个=0.3，2个=0.6，3个+=1.0）'],
            ['权重', '默认 1.0，可调整为 0.5~2.0'],
            ['新鲜度', 'hot_value/10000（0~1.0）'],
            ['最终得分', 'keyword_score × weight + freshness × 0.1'],
          ].map(([label, desc]) => (
            <div key={label} className="flex gap-2 text-xs">
              <span className="min-w-[60px] font-semibold text-ink-700">{label}</span>
              <span className="text-ink-500">{desc}</span>
            </div>
          ))}
        </div>
      </Panel>
    </AdminPageShell>
  );
}
