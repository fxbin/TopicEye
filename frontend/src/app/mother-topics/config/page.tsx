'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, ArrowRight, Settings } from 'lucide-react';
import { motherTopicsApi, type MotherTopic } from '@/lib/api';
import { Badge, Button, Panel, Toolbar } from '@/components/ui';
import { FieldLabel } from '@/components/form';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';

/* ── helpers ── */

function TopicCard({
  topic,
  onSave,
  onDelete,
}: {
  topic: MotherTopic;
  onSave: (updated: Partial<MotherTopic>) => void;
  onDelete: (id: number) => void;
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

  const handleSave = async () => {
    setSaving(true);
    const keywords = form.keywords.split(',').map(k => k.trim()).filter(Boolean);
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
    setSaving(false);
    setEditing(false);
  };

  const contentTypeColor: Record<string, string> = {
    '工具评测': '#6366f1',
    '方法论': '#10b981',
    '观察': '#f59e0b',
    '随笔': '#ec4899',
    '教程': '#0ea5e9',
    '观点': '#8b5cf6',
  };

  return (
    <Panel className="mb-4 p-5">
      {/* card header */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <h3 className="m-0 text-base font-bold text-gray-900">{topic.name}</h3>
            {topic.content_type && (
              <span style={{
                background: `${contentTypeColor[topic.content_type] || '#6366f1'}15`,
                color: contentTypeColor[topic.content_type] || '#6366f1',
              }} className="rounded-sm px-2 py-0.5 text-[11px] font-medium">
                {topic.content_type}
              </span>
            )}
          </div>
          {topic.description && (
            <p className="m-0 mt-0.5 text-xs leading-5 text-gray-500">
              {topic.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">权重 {topic.weight}</span>
          {!topic.is_active && (
            <Badge tone="red" className="rounded-sm px-2 py-0.5 text-[11px]">已停用</Badge>
          )}
        </div>
      </div>

      {editing ? (
        /* edit form */
        <div className="flex flex-col gap-3">
          <div>
            <FieldLabel>名称</FieldLabel>
            <input
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              className="w-full rounded-xs border border-gray-300 px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </div>
          <div>
            <FieldLabel>描述</FieldLabel>
            <input
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              className="w-full rounded-xs border border-gray-300 px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </div>
          <div>
            <FieldLabel>关键词（逗号分隔）</FieldLabel>
            <textarea
              value={form.keywords}
              onChange={e => setForm({ ...form, keywords: e.target.value })}
              rows={4}
              className="w-full resize-y rounded-xs border border-gray-300 px-2.5 py-1.5 font-mono text-xs outline-none focus:border-primary"
            />
            <div className="mt-1 text-[11px] text-gray-400">
              当前 {form.keywords.split(',').filter(k => k.trim()).length} 个关键词
            </div>
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <FieldLabel>权重乘数</FieldLabel>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="3"
                value={form.weight}
                onChange={e => setForm({ ...form, weight: parseFloat(e.target.value) })}
                className="w-full rounded-xs border border-gray-300 px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
              />
            </div>
            <div className="flex-1">
              <FieldLabel>目标读者</FieldLabel>
              <input
                value={form.target_reader}
                onChange={e => setForm({ ...form, target_reader: e.target.value })}
                className="w-full rounded-xs border border-gray-300 px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
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
            <div className="mb-1.5 text-xs font-semibold text-gray-700">
              关键词 ({topic.keywords.length})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {topic.keywords.slice(0, 20).map(kw => (
                <Badge key={kw} tone="neutral" className="rounded-full px-2.5 py-1 text-xs">{kw}</Badge>
              ))}
              {topic.keywords.length > 20 && (
                <span className="px-2 py-1 text-xs text-gray-400">
                  +{topic.keywords.length - 20} 更多
                </span>
              )}
            </div>
          </div>

          {/* target reader */}
          {topic.target_reader && (
            <div className="mb-3 text-xs text-gray-500">
              <b>目标读者:</b> {topic.target_reader}
            </div>
          )}

          {/* actions */}
          <Toolbar className="mt-3 border-t border-gray-100 pt-3">
            <Button
              type="button"
              onClick={() => setEditing(true)}
              variant="primary"
              className="min-h-0 px-3.5 py-1.5 text-xs font-medium"
            >
              编辑
            </Button>
            <Button
              type="button"
              onClick={() => onDelete(topic.id)}
              variant="danger"
              className="min-h-0 px-3.5 py-1.5 text-xs font-medium"
            >
              停用
            </Button>
          </Toolbar>
        </>
      )}
    </Panel>
  );
}

/* ── Main Page ── */

export default function MotherTopicsConfigPage() {
  const router = useRouter();
  const { data: topics, loading, error, refetch } = useFetch<MotherTopic[]>(
    async () => {
      const ts = await motherTopicsApi.list(false);
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
    <div className="max-w-[860px] px-6 py-5">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="mb-1 text-[22px] font-bold text-gray-900">
            <span className="inline-flex items-center gap-2">
              <Settings size={20} className="text-primary" strokeWidth={2.1} />
              母题配置
            </span>
          </h1>
          <p className="m-0 text-[13px] text-gray-500">
            配置你的公众号内容支柱，调整关键词以精准匹配你的写作方向
          </p>
        </div>
        <Button
          type="button"
          onClick={() => router.push('/my-topics')}
          variant="secondary"
          className="text-[13px] font-medium"
        >
          <ArrowLeft size={14} strokeWidth={2} />
          返回我的母题
        </Button>
      </div>

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
      <Panel className="mt-8 bg-gray-50 p-4">
        <h3 className="mb-3 text-sm font-bold text-gray-700">打分公式详解</h3>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2">
          {[
            ['母题匹配', '0.0~1.0（匹配1个=0.3，2个=0.6，3个+=1.0）'],
            ['权重', '默认 1.0，可调整为 0.5~2.0'],
            ['新鲜度', 'hot_value/10000（0~1.0）'],
            ['最终得分', 'keyword_score × weight + freshness × 0.1'],
          ].map(([label, desc]) => (
            <div key={label} className="flex gap-2 text-xs">
              <span className="min-w-[60px] font-semibold text-gray-700">{label}</span>
              <span className="text-gray-500">{desc}</span>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
