'use client';

import React, { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  ArrowRight,
  Copy,
  Lock,
  Plus,
  RefreshCw,
  Settings,
  Sparkles,
} from 'lucide-react';
import { motherTopicsApi, type MotherTopic } from '@/lib/api';
import { Badge, Button, Panel, Toolbar, cx } from '@/components/ui';
import { FieldLabel } from '@/components/form';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import { useAppContext } from '@/components/ClientLayout';

/* ── helpers ── */

function isSystemTemplate(topic: MotherTopic): boolean {
  return topic.owner_user_id === null;
}

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
  const [saving, setSaving] = useState(false);
  const isSystem = isSystemTemplate(topic);
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
    <Panel className={cx('mb-4 p-5', isSystem && 'border-gray-200 bg-gray-50/50')}>
      {/* card header */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h3 className="m-0 text-base font-bold text-gray-900">{topic.name}</h3>
            {topic.content_type && (
              <span style={{
                background: `${contentTypeColor[topic.content_type] || '#6366f1'}15`,
                color: contentTypeColor[topic.content_type] || '#6366f1',
              }} className="rounded-sm px-2 py-0.5 text-[11px] font-medium">
                {topic.content_type}
              </span>
            )}
            {isSystem ? (
              <Badge tone="neutral" className="gap-1 rounded-sm px-2 py-0.5 text-[11px]">
                <Lock size={10} /> 系统模板
              </Badge>
            ) : (
              <Badge tone="primary" className="rounded-sm px-2 py-0.5 text-[11px]">我的</Badge>
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

          {topic.target_reader && (
            <div className="mb-3 text-xs text-gray-500">
              <b>目标读者:</b> {topic.target_reader}
            </div>
          )}

          <Toolbar className="mt-3 border-t border-gray-100 pt-3">
            {isSystem ? (
              <span className="text-xs text-gray-400">
                系统模板只读，如需修改请先 fork 到自己的母题
              </span>
            ) : (
              <>
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
              </>
            )}
          </Toolbar>
        </>
      )}
    </Panel>
  );
}

/* ── New Topic Form ── */

function NewTopicForm({ onCreate }: { onCreate: (data: Partial<MotherTopic>) => Promise<void> }) {
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: '',
    description: '',
    keywords: '',
    weight: 1.0,
    target_reader: '',
  });

  const handleSubmit = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const keywords = form.keywords.split(',').map(k => k.trim()).filter(Boolean);
      await onCreate({
        name: form.name.trim(),
        description: form.description || undefined,
        keywords,
        weight: form.weight,
        target_reader: form.target_reader || undefined,
        is_active: true,
        display_order: 99,
      });
      setForm({ name: '', description: '', keywords: '', weight: 1.0, target_reader: '' });
      setExpanded(false);
    } finally {
      setSaving(false);
    }
  };

  if (!expanded) {
    return (
      <Panel className="mb-4 border-dashed border-2 border-gray-200 p-4">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="flex w-full items-center justify-center gap-2 text-sm font-bold text-gray-500 hover:text-primary"
        >
          <Plus size={16} /> 新建我的母题
        </button>
      </Panel>
    );
  }

  return (
    <Panel className="mb-4 border-primary-border bg-primary-light/30 p-5">
      <div className="mb-3 flex items-center gap-2 text-sm font-bold text-gray-900">
        <Plus size={16} className="text-primary" /> 新建母题
      </div>
      <div className="flex flex-col gap-3">
        <div>
          <FieldLabel>名称 *</FieldLabel>
          <input
            value={form.name}
            onChange={e => setForm({ ...form, name: e.target.value })}
            placeholder="如：AI 工具评测"
            className="w-full rounded-xs border border-gray-300 px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
          />
        </div>
        <div>
          <FieldLabel>关键词（逗号分隔）</FieldLabel>
          <textarea
            value={form.keywords}
            onChange={e => setForm({ ...form, keywords: e.target.value })}
            rows={3}
            placeholder="AI工具, ChatGPT, 效率"
            className="w-full resize-y rounded-xs border border-gray-300 px-2.5 py-1.5 font-mono text-xs outline-none focus:border-primary"
          />
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
              placeholder="对效率提升有兴趣的创作者"
              className="w-full rounded-xs border border-gray-300 px-2.5 py-1.5 text-[13px] outline-none focus:border-primary"
            />
          </div>
        </div>
        <Toolbar className="gap-2">
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={saving || !form.name.trim()}
            variant="primary"
            className="min-h-0 px-4 py-1.5 text-[13px] font-medium"
          >
            {saving ? '创建中...' : '创建'}
          </Button>
          <Button
            type="button"
            onClick={() => setExpanded(false)}
            variant="ghost"
            className="min-h-0 px-4 py-1.5 text-[13px] font-medium"
          >
            取消
          </Button>
        </Toolbar>
      </div>
    </Panel>
  );
}

/* ── Main Page ── */

export default function MyTopicsConfigPage() {
  const router = useRouter();
  const { currentUser } = useAppContext();
  const isAdmin = currentUser?.role === 'admin';

  const { data, loading, error, refetch } = useFetch<{
    topics: MotherTopic[];
    hasOwnTopics: boolean;
  }>(async () => {
    const ts = await motherTopicsApi.list(false);
    const sorted = ts.sort((a, b) => {
      // 自己的母题优先，再按 display_order
      const aOwn = a.owner_user_id !== null ? 0 : 1;
      const bOwn = b.owner_user_id !== null ? 0 : 1;
      if (aOwn !== bOwn) return aOwn - bOwn;
      return a.display_order - b.display_order;
    });
    return {
      topics: sorted,
      hasOwnTopics: ts.some(t => t.owner_user_id !== null),
    };
  }, []);

  const [forking, setForking] = useState(false);

  const handleForkDefaults = useCallback(async () => {
    setForking(true);
    try {
      await motherTopicsApi.forkDefaults();
      await refetch();
    } finally {
      setForking(false);
    }
  }, [refetch]);

  const handleSave = async (id: number, updated: Partial<MotherTopic>) => {
    await motherTopicsApi.update(id, updated);
    await refetch();
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确认停用此母题？停用后相关推荐将不再出现。')) return;
    await motherTopicsApi.delete(id);
    await refetch();
  };

  const handleCreate = async (data: Partial<MotherTopic>) => {
    await motherTopicsApi.create(data as Parameters<typeof motherTopicsApi.create>[0]);
    await refetch();
  };

  const topics = data?.topics ?? [];
  const hasOwnTopics = data?.hasOwnTopics ?? false;
  const myTopics = topics.filter(t => t.owner_user_id !== null);
  const systemTopics = topics.filter(t => t.owner_user_id === null);

  return (
    <div className="h-full overflow-y-auto bg-[linear-gradient(180deg,#F8FAFC_0%,#F4F6F8_44%,#EEF2F5_100%)] px-4 pb-8 sm:px-6 lg:px-10">
      <header className="sticky top-0 z-10 -mx-4 border-b border-gray-200 bg-[#F8FAFC]/90 px-4 py-4 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
        <div className="mx-auto flex max-w-[860px] flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <Settings size={18} className="text-primary" strokeWidth={2.2} />
              <h1 className="m-0 text-xl font-black text-gray-900">母题配置</h1>
            </div>
            <p className="mt-1.5 text-xs leading-5 text-gray-500">
              管理你的内容支柱母题，调整关键词以精准匹配你的写作方向
            </p>
          </div>
          <button
            type="button"
            onClick={() => router.push('/my-topics')}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-sm border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-700 no-underline hover:border-primary-border hover:text-primary"
          >
            <ArrowLeft size={14} strokeWidth={2} /> 返回我的母题
          </button>
        </div>
      </header>

      <main className="mx-auto mt-5 max-w-[860px]">
        {/* Info box */}
        <Panel className="mb-6 border-teal-border bg-teal-light px-4 py-3 text-[13px] leading-6 text-teal">
          <b>打分规则:</b> 母题匹配分 × 权重 + 新鲜度加成 <ArrowRight size={13} strokeWidth={2} className="inline align-[-2px]" /> 最终得分<br/>
          <b>阈值:</b> 80+ 今日主选题 / 65-79 值得储备 / 50-64 观察池 / &lt;50 过滤
        </Panel>

        {/* Admin notice */}
        {isAdmin && (
          <Panel className="mb-6 border-amber-border bg-amber-light px-4 py-3 text-[13px] leading-6 text-amber-700">
            <b>管理员提示:</b> 你当前以管理员身份登录，新建的母题会作为系统模板（所有用户可见且只读）。
            如需配置个人母题，请切换到普通用户账号。
          </Panel>
        )}

        {/* Fork banner: 首次进入且没有自己的母题时提示 fork */}
        {!isAdmin && !hasOwnTopics && !loading && (
          <Panel className="mb-6 border-primary-border bg-primary-light px-4 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-[14px] font-black text-primary">
                  <Sparkles size={16} /> 从系统模板开始
                </div>
                <p className="mt-1 text-xs leading-5 text-gray-600">
                  你还没有自己的母题。fork 一份系统模板作为起点，然后按需调整关键词和权重。
                </p>
              </div>
              <Button
                type="button"
                onClick={handleForkDefaults}
                disabled={forking}
                variant="primary"
                className="min-h-9"
              >
                {forking ? <RefreshCw size={14} className="animate-spin" /> : <Copy size={14} />}
                {forking ? 'fork 中...' : 'fork 系统模板'}
              </Button>
            </div>
          </Panel>
        )}

        {error && (
          <div className="mb-4">
            <ErrorState error={error} onRetry={() => void refetch()} panel={false} />
          </div>
        )}

        {loading ? (
          <LoadingState label="加载中…" minHeight="160px" />
        ) : (
          <>
            {/* 我的母题 */}
            {myTopics.length > 0 && (
              <section className="mb-6">
                <h2 className="mb-3 text-sm font-bold text-gray-700">
                  我的母题 ({myTopics.length})
                </h2>
                {!isAdmin && <NewTopicForm onCreate={handleCreate} />}
                {myTopics.map(topic => (
                  <TopicCard
                    key={topic.id}
                    topic={topic}
                    onSave={updated => handleSave(topic.id, updated)}
                    onDelete={handleDelete}
                  />
                ))}
              </section>
            )}

            {/* 系统模板库 */}
            {systemTopics.length > 0 && (
              <section className="mb-6">
                <h2 className="mb-3 text-sm font-bold text-gray-700">
                  系统模板库 ({systemTopics.length})
                </h2>
                <p className="mb-3 text-xs text-gray-500">
                  系统模板由官方维护，所有用户只读。如需个性化，fork 后在自己的副本上修改。
                </p>
                {systemTopics.map(topic => (
                  <TopicCard
                    key={topic.id}
                    topic={topic}
                    onSave={updated => handleSave(topic.id, updated)}
                    onDelete={handleDelete}
                  />
                ))}
              </section>
            )}

            {/* 空状态 */}
            {topics.length === 0 && (
              <Panel className="grid min-h-[200px] place-items-center p-9 text-center">
                <div>
                  <Settings size={28} className="mx-auto text-gray-300" strokeWidth={1.8} />
                  <div className="mt-3 text-sm font-bold text-gray-700">还没有任何母题</div>
                  <div className="mt-1.5 text-xs text-gray-400">
                    {isAdmin
                      ? '作为管理员，你可以新建系统模板供所有用户使用。'
                      : '新建一个母题，或 fork 系统模板作为起点。'}
                  </div>
                </div>
              </Panel>
            )}
          </>
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
      </main>
    </div>
  );
}
