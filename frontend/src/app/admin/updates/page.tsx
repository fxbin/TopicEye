'use client';

import React, { useState } from 'react';
import {
  CheckCircle2,
  CircleDot,
  Edit3,
  Loader2,
  Plus,
  RefreshCw,
  Rocket,
  Trash2,
  X,
} from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import {
  productFeedbackApi,
  type ProductUpdateItem,
  type ProductUpdateEntry,
  type ProductUpdateKind,
  type ProductUpdateStatus,
} from '@/lib/api';

const KIND_OPTIONS: { value: ProductUpdateKind; label: string; tone: 'teal' | 'primary' | 'purple' | 'amber' }[] = [
  { value: 'release', label: '发布', tone: 'teal' },
  { value: 'improvement', label: '改进', tone: 'primary' },
  { value: 'fix', label: '修复', tone: 'purple' },
  { value: 'roadmap', label: '规划', tone: 'amber' },
];

const STATUS_OPTIONS: { value: ProductUpdateStatus; label: string; tone: 'amber' | 'primary' | 'teal' }[] = [
  { value: 'planned', label: '已规划', tone: 'amber' },
  { value: 'in_progress', label: '进行中', tone: 'primary' },
  { value: 'shipped', label: '已发布', tone: 'teal' },
];

const STATUS_TONES: Record<ProductUpdateStatus, 'amber' | 'primary' | 'teal'> = {
  planned: 'amber',
  in_progress: 'primary',
  shipped: 'teal',
};

const STATUS_LABELS: Record<ProductUpdateStatus, string> = {
  planned: '已规划',
  in_progress: '进行中',
  shipped: '已发布',
};

interface DraftEntry {
  kind: ProductUpdateKind;
  description: string;
}

const EMPTY_DRAFT = {
  version: '',
  status: 'planned' as ProductUpdateStatus,
  target_date: '',
  shipped_at: '',
  items: [] as DraftEntry[],
};

function toDateInput(iso: string | null | undefined): string {
  if (!iso) return '';
  return iso.slice(0, 10);
}

function fromDateInput(s: string): string | null {
  if (!s) return null;
  return new Date(`${s}T00:00:00Z`).toISOString();
}

export default function AdminUpdatesPage() {
  const { currentUser, authLoading } = useAppContext();
  const [statusFilter, setStatusFilter] = useState<'all' | ProductUpdateStatus>('all');
  const [versionQuery, setVersionQuery] = useState('');
  const [editing, setEditing] = useState<ProductUpdateItem | null>(null);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const { data: items, loading, error: fetchError, refetch } = useFetch<ProductUpdateItem[]>(
    () => productFeedbackApi.listUpdates({ limit: 100 }).then(r => r.items),
    [],
    { enabled: !authLoading },
  );

  const openCreate = () => {
    setDraft(EMPTY_DRAFT);
    setEditing(null);
    setShowCreate(true);
    setFormError(null);
    setNotice(null);
  };

  const openEdit = (item: ProductUpdateItem) => {
    setEditing(item);
    setDraft({
      version: item.version,
      status: item.status,
      target_date: toDateInput(item.target_date),
      shipped_at: toDateInput(item.shipped_at),
      items: item.items.map((it) => ({ kind: it.kind, description: it.description })),
    });
    setShowCreate(true);
    setFormError(null);
    setNotice(null);
  };

  const closeDialog = () => {
    setShowCreate(false);
    setEditing(null);
  };

  const addItem = () => {
    setDraft({ ...draft, items: [...draft.items, { kind: 'improvement', description: '' }] });
  };

  const removeItem = (idx: number) => {
    setDraft({ ...draft, items: draft.items.filter((_, i) => i !== idx) });
  };

  const updateItem = (idx: number, patch: Partial<DraftEntry>) => {
    setDraft({
      ...draft,
      items: draft.items.map((it, i) => (i === idx ? { ...it, ...patch } : it)),
    });
  };

  const handleSave = async () => {
    if (!draft.version.trim()) {
      setFormError('请填写版本号');
      return;
    }
    if (draft.items.length === 0) {
      setFormError('至少添加一个更新项');
      return;
    }
    if (draft.items.some((it) => !it.description.trim())) {
      setFormError('所有更新项必须有描述');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        version: draft.version.trim(),
        status: draft.status,
        target_date: fromDateInput(draft.target_date),
        shipped_at: fromDateInput(draft.shipped_at),
        items: draft.items.map((it, idx) => ({
          id: 0,
          kind: it.kind,
          description: it.description.trim(),
          order_index: idx,
        })),
      };
      if (editing) {
        await productFeedbackApi.updateProductUpdate(editing.id, payload);
        setNotice(`已更新 v${payload.version}`);
      } else {
        await productFeedbackApi.createUpdate(payload);
        setNotice(`已创建 v${payload.version}`);
      }
      await refetch();
      closeDialog();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (item: ProductUpdateItem) => {
    if (!confirm(`确定要删除 v${item.version} 吗？此操作不可恢复。`)) {
      return;
    }
    try {
      // productFeedbackApi 没有 delete 方法，直接走 request
      const res = await fetch(`/api/v1/product-feedback/updates/${item.id}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) {
        throw new Error(`删除失败: HTTP ${res.status}`);
      }
      setNotice(`已删除 v${item.version}`);
      await refetch();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : String(err));
    }
  };

  if (authLoading || loading) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page">
        <div className="inline-flex items-center gap-2 text-sm font-bold text-gray-500">
          <Loader2 size={16} className="animate-spin" />
          正在加载发版管理
        </div>
      </div>
    );
  }

  if (!currentUser || currentUser.role !== 'admin') {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-page p-6">
        <Panel className="max-w-md p-6 text-center">
          <h2 className="mb-2 text-base font-semibold text-gray-900">需要管理员权限</h2>
          <p className="text-[13px] text-gray-500">发版记录管理仅对管理员开放。</p>
        </Panel>
      </div>
    );
  }

  const shippedCount = (items || []).filter((it) => it.status === 'shipped').length;
  const inProgressCount = (items || []).filter((it) => it.status === 'in_progress').length;
  const plannedCount = (items || []).filter((it) => it.status === 'planned').length;

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-page px-4 py-5 sm:px-6 lg:px-10">
      <div className="mx-auto w-full max-w-[1100px] space-y-5 pb-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-[26px] font-black text-gray-900">
              <Rocket size={22} className="text-orange" />
              发版记录管理
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              创建和编辑产品发版记录 · 用户在「更新记录」页面看到的就是这里的内容
            </p>
          </div>
          <div className="flex gap-2">
            <Button type="button" onClick={openCreate}>
              <Plus size={14} />
              新建发版
            </Button>
            <Button type="button" variant="secondary" onClick={() => void refetch()}>
              <RefreshCw size={14} />
              刷新
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="总发版" value={(items || []).length} tone="neutral" />
          <StatTile label="已发布" value={shippedCount} tone="teal" />
          <StatTile label="进行中" value={inProgressCount} tone="primary" />
          <StatTile label="已规划" value={plannedCount} tone="amber" />
        </div>

        {fetchError && (
          <div className="mb-4">
            <ErrorState error={fetchError} onRetry={() => void refetch()} panel={false} />
          </div>
        )}
        {formError && (
          <div className="mb-4 rounded-sm border border-red-light bg-red-light px-4 py-2.5 text-[13px] text-red">
            {formError}
          </div>
        )}
        {notice && !fetchError && !formError && (
          <div className="rounded-sm border border-teal-border bg-teal-light/30 px-4 py-2.5 text-[13px] text-teal">
            {notice}
          </div>
        )}

        {(items || []).length === 0 ? (
          <Panel className="p-8 text-center">
            <p className="text-[14px] text-gray-500">还没有发版记录，点右上角「新建发版」开始。</p>
          </Panel>
        ) : (
          <>
            {/* Filter row: status tabs + version search */}
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                value={versionQuery}
                onChange={(e) => setVersionQuery(e.target.value)}
                placeholder="按版本号搜索"
                className="flex-1 min-w-[180px] rounded-sm border border-gray-200 bg-white px-3 py-1 text-[12px] focus:border-orange focus:outline-none"
              />
              {([
                { value: 'all', label: '全部', count: (items || []).length },
                { value: 'shipped', label: '已发布', count: (items || []).filter((i) => i.status === 'shipped').length },
                { value: 'in_progress', label: '进行中', count: (items || []).filter((i) => i.status === 'in_progress').length },
                { value: 'planned', label: '已规划', count: (items || []).filter((i) => i.status === 'planned').length },
              ] as const).map((tab) => (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => setStatusFilter(tab.value as 'all' | ProductUpdateStatus)}
                  className={cx(
                    'flex items-center gap-1.5 rounded-sm border px-3 py-1 text-[12px] transition',
                    statusFilter === tab.value
                      ? 'border-orange bg-orange text-white'
                      : 'border-gray-200 bg-white text-gray-700 hover:border-orange/50',
                  )}
                >
                  {tab.label}
                  <span className={cx(
                    'rounded-full px-1.5 text-[10px]',
                    statusFilter === tab.value ? 'bg-white/20' : 'bg-gray-100',
                  )}>
                    {tab.count}
                  </span>
                </button>
              ))}
            </div>

            {/* Filtered list */}
            {(() => {
              const filtered = (items || [])
                .filter((u) => statusFilter === 'all' || u.status === statusFilter)
                .filter((u) => !versionQuery.trim() || u.version.toLowerCase().includes(versionQuery.trim().toLowerCase()));
              if (filtered.length === 0) {
                return (
                  <Panel className="p-6 text-center">
                    <p className="text-[13px] text-gray-500">
                      {versionQuery.trim()
                        ? `没有匹配「${versionQuery}」的发版记录`
                        : statusFilter === 'all'
                          ? '没有发版记录'
                          : `没有「${statusFilter}」状态的发版记录`}
                    </p>
                  </Panel>
                );
              }
              return (
                <div className="space-y-2.5">
                  {filtered.map((item) => (
                    <UpdateAdminRow
                      key={item.id}
                      item={item}
                      onEdit={() => openEdit(item)}
                      onDelete={() => void handleDelete(item)}
                    />
                  ))}
                </div>
              );
            })()}
          </>
        )}
      </div>

      {showCreate && (
        <UpdateEditor
          draft={draft}
          editing={editing}
          saving={saving}
          error={formError}
          onChange={setDraft}
          onAddItem={addItem}
          onRemoveItem={removeItem}
          onUpdateItem={updateItem}
          onSave={handleSave}
          onClose={closeDialog}
        />
      )}
    </div>
  );
}

function StatTile({ label, value, tone }: { label: string; value: number; tone: 'neutral' | 'teal' | 'primary' | 'amber' }) {
  return (
    <div className="rounded-sm border border-gray-200 bg-white px-4 py-3 shadow-sm">
      <div className="mb-1 text-[12px] text-gray-500">{label}</div>
      <div className="flex items-end gap-2">
        <span className="font-mono text-2xl font-semibold text-gray-900">{value}</span>
        <Badge tone={tone} className="mb-0.5">条</Badge>
      </div>
    </div>
  );
}

function UpdateAdminRow({ item, onEdit, onDelete }: { item: ProductUpdateItem; onEdit: () => void; onDelete: () => void }) {
  return (
    <Panel className="p-3.5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2">
            <span className="font-mono text-[15px] font-black text-gray-900">{item.version}</span>
            <Badge tone={STATUS_TONES[item.status]}>{STATUS_LABELS[item.status]}</Badge>
            <span className="text-[12px] text-gray-500">
              {item.shipped_at ? `发布于 ${item.shipped_at.slice(0, 10)}` :
                item.target_date ? `计划 ${item.target_date}` : '近期规划'}
            </span>
          </div>
          <p className="text-[12px] text-gray-500">
            {item.items.length} 个更新项
          </p>
        </div>
        <div className="flex flex-shrink-0 gap-1.5">
          <Button type="button" variant="secondary" onClick={onEdit} className="!px-2 !py-1 text-[12px]">
            <Edit3 size={12} />编辑
          </Button>
          <Button type="button" variant="ghost" onClick={onDelete} className="!px-2 !py-1 text-[12px] text-red hover:!text-red">
            <Trash2 size={12} />删除
          </Button>
        </div>
      </div>
    </Panel>
  );
}

function UpdateEditor({
  draft, editing, saving, error, onChange, onAddItem, onRemoveItem, onUpdateItem, onSave, onClose,
}: {
  draft: typeof EMPTY_DRAFT;
  editing: ProductUpdateItem | null;
  saving: boolean;
  error: string | null;
  onChange: (next: typeof EMPTY_DRAFT) => void;
  onAddItem: () => void;
  onRemoveItem: (idx: number) => void;
  onUpdateItem: (idx: number, patch: Partial<DraftEntry>) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 sm:p-6">
      <div className="flex h-full max-h-[90vh] w-full max-w-2xl flex-col rounded-md bg-white shadow-xl">
        <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-200 px-5 py-3.5">
          <h2 className="text-base font-semibold text-gray-900">
            {editing ? `编辑 v${editing.version}` : '新建发版'}
          </h2>
          <Button type="button" variant="ghost" onClick={onClose} className="!px-2 !py-1">
            <X size={16} />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {error && (
            <div className="mb-3 rounded-sm border border-red-light bg-red-light/30 px-3 py-2 text-[13px] text-red">
              {error}
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[12px] font-medium text-gray-700">版本号 *</label>
              <input
                type="text"
                value={draft.version}
                onChange={(e) => onChange({ ...draft, version: e.target.value })}
                placeholder="如 v0.2.0"
                className="w-full rounded-sm border border-gray-200 bg-white px-3 py-1.5 text-[13px] focus:border-orange focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-gray-700">状态</label>
              <div className="flex gap-1.5">
                {STATUS_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => onChange({ ...draft, status: opt.value })}
                    className={cx(
                      'rounded-sm border px-3 py-1 text-[12px] transition',
                      draft.status === opt.value
                        ? 'border-orange bg-orange text-white'
                        : 'border-gray-200 bg-white text-gray-700 hover:border-orange/50',
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-gray-700">计划日期</label>
              <input
                type="date"
                value={draft.target_date}
                onChange={(e) => onChange({ ...draft, target_date: e.target.value })}
                className="w-full rounded-sm border border-gray-200 bg-white px-3 py-1.5 text-[13px] focus:border-orange focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-gray-700">发布日期</label>
              <input
                type="date"
                value={draft.shipped_at}
                onChange={(e) => onChange({ ...draft, shipped_at: e.target.value })}
                className="w-full rounded-sm border border-gray-200 bg-white px-3 py-1.5 text-[13px] focus:border-orange focus:outline-none"
              />
            </div>
          </div>

          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[13px] font-semibold text-gray-900">更新项 *</h3>
              <Button type="button" variant="secondary" onClick={onAddItem} className="!px-2.5 !py-1 text-[12px]">
                <Plus size={12} />添加一项
              </Button>
            </div>
            {draft.items.length === 0 ? (
              <p className="rounded-sm bg-gray-50 px-3 py-3 text-center text-[12px] text-gray-500">
                还没有更新项
              </p>
            ) : (
              <ul className="space-y-2">
                {draft.items.map((it, idx) => (
                  <li key={idx} className="rounded-sm border border-gray-200 bg-white p-2.5">
                    <div className="mb-1.5 flex items-center gap-1.5">
                      {KIND_OPTIONS.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => onUpdateItem(idx, { kind: opt.value })}
                          className={cx(
                            'rounded-sm border px-2 py-0.5 text-[11px] transition',
                            it.kind === opt.value
                              ? 'border-orange bg-orange text-white'
                              : 'border-gray-200 bg-white text-gray-700 hover:border-orange/50',
                          )}
                        >
                          {opt.label}
                        </button>
                      ))}
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => onRemoveItem(idx)}
                        className="!ml-auto !px-1.5 !py-0.5 text-red hover:!text-red"
                      >
                        <Trash2 size={12} />
                      </Button>
                    </div>
                    <textarea
                      value={it.description}
                      onChange={(e) => onUpdateItem(idx, { description: e.target.value })}
                      rows={2}
                      maxLength={500}
                      placeholder="描述这次更新（用户看到的文案）"
                      className="w-full rounded-sm border border-gray-200 bg-white px-2.5 py-1.5 text-[13px] focus:border-orange focus:outline-none"
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <div className="flex flex-shrink-0 justify-end gap-2 border-t border-gray-200 px-5 py-3">
          <Button type="button" variant="secondary" onClick={onClose}>取消</Button>
          <Button type="button" onClick={onSave} disabled={saving}>
            {saving && <Loader2 size={14} className="animate-spin" />}
            {editing ? '保存修改' : '创建'}
          </Button>
        </div>
      </div>
    </div>
  );
}
