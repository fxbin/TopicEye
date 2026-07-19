'use client';

import React, { useState, useCallback } from 'react';
import {
  AlertTriangle,
  Loader2,
  Plus,
  RadioTower,
  Search,
  X,
} from 'lucide-react';
import { sourcesApi } from '@/lib/api';
import type { CreateSourceRequest, UpdateSourceRequest } from '@/lib/api';
import type { SyncResult } from '@/types';
import { Badge, Button, Panel, cx } from '@/components/ui';
import SourceForm, { FormState, emptyForm } from '@/components/SourceForm';
import type { BackendSource } from '@/components/SourceRow';
import { timeAgo } from '@/lib/utils';
import { LoadingState, EmptyState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';

// ─── Page Component ───
//
// User-facing page for managing private (user-owned) sources.
// Visual shell aligned with /my-topics/config (sticky header + gradient
// background + max-w container + card-based list). Uses a dedicated
// PrivateSourceCard instead of the admin 9-column grid row, because the
// private scenario has no batch-select / favorite columns and a card layout
// reads better in the narrow container.

type FormMode = 'create' | 'edit';

const PAGE_SIZE = 50;

export default function MySourcesPage() {
  const [searchKeyword, setSearchKeyword] = useState('');

  // Fetch state via useFetch (aligned with project convention)
  const { data, loading, error, refetch } = useFetch<{
    items: BackendSource[];
    total: number;
  }>(async () => {
    const res = await sourcesApi.listMine({
      page: 1,
      page_size: PAGE_SIZE,
      keyword: searchKeyword.trim() || undefined,
    });
    const list = (res?.items || []) as BackendSource[];
    return { items: list, total: res?.total ?? list.length };
  }, [searchKeyword]);

  // Action-level state (separate from fetch state)
  const [actionError, setActionError] = useState<string | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<BackendSource | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [submitting, setSubmitting] = useState(false);

  const [lastSync, setLastSync] = useState<SyncResult | null>(null);
  const [syncingId, setSyncingId] = useState<number | null>(null);

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  // ─── Create ───
  const handleOpenCreate = useCallback(() => {
    setEditing(null);
    setForm(emptyForm);
    setPlanError(null);
    setActionError(null);
    setShowForm(true);
  }, []);

  // ─── Edit ───
  const handleEdit = useCallback((source: BackendSource) => {
    setEditing(source);
    setForm({
      name: source.name,
      source_type: source.source_type as FormState['source_type'],
      url: source.url,
      keyword: source.keyword || '',
      category: source.category || '',
      weight: source.weight || 3,
      fetch_interval_minutes: source.fetch_interval_minutes || 60,
      enabled: source.enabled !== false,
    });
    setPlanError(null);
    setActionError(null);
    setShowForm(true);
  }, []);

  // ─── Submit (create or edit) ───
  const handleSubmit = async () => {
    if (!form.name.trim()) {
      setActionError('请输入信源名称');
      return;
    }
    if (!form.url.trim()) {
      setActionError('请输入信源 URL');
      return;
    }
    try {
      setSubmitting(true);
      setActionError(null);
      setPlanError(null);
      const payload = {
        name: form.name.trim(),
        source_type: form.source_type,
        url: form.url.trim(),
        keyword: form.keyword.trim() || null,
        category: form.category || null,
        weight: form.weight,
        fetch_interval_minutes: form.fetch_interval_minutes,
        enabled: form.enabled,
      } as CreateSourceRequest;

      if (editing) {
        await sourcesApi.updateMine(editing.id, payload as UpdateSourceRequest);
      } else {
        await sourcesApi.createMine(payload);
      }
      setShowForm(false);
      setEditing(null);
      setForm(emptyForm);
      await refetch();
    } catch (err: unknown) {
      const e = err as { status?: number; message?: string; detail?: string };
      if (e?.status === 403 || e?.message?.includes('套餐') || e?.message?.includes('Pro')) {
        setPlanError(e?.detail || e?.message || '当前套餐不支持创建私有信源，请升级到 Pro 及以上');
      } else {
        setActionError(e instanceof Error ? e.message : (editing ? '更新失败' : '创建失败'));
      }
    } finally {
      setSubmitting(false);
    }
  };

  // ─── Delete ───
  const handleDelete = async (source: BackendSource) => {
    if (!confirm(`确定删除「${source.name}」吗？\n该操作不可撤销。`)) return;
    try {
      await sourcesApi.deleteMine(source.id);
      await refetch();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : '删除失败');
    }
  };

  // ─── Sync ───
  const handleSync = async (source: BackendSource) => {
    if (!source.enabled) {
      setActionError('信源已禁用，请先启用再同步');
      return;
    }
    try {
      setSyncingId(source.id);
      const result = await sourcesApi.syncMine(source.id);
      setLastSync(result);
      await refetch();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : '同步失败');
    } finally {
      setSyncingId(null);
    }
  };

  // ─── Render ───
  return (
    <div className="h-full overflow-y-auto bg-[linear-gradient(180deg,#F8FAFC_0%,#F4F6F8_44%,#EEF2F5_100%)] px-4 pb-8 sm:px-6 lg:px-10">
      <header className="sticky top-0 z-10 -mx-4 border-b border-gray-200 bg-[#F8FAFC]/90 px-4 py-4 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
        <div className="mx-auto flex max-w-[860px] flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <RadioTower size={18} className="text-primary" strokeWidth={2.2} />
              <h1 className="m-0 text-xl font-black text-gray-900">我的信源</h1>
              <Badge tone="teal" className="font-mono text-[10px]">{total}</Badge>
            </div>
            <p className="mt-1.5 text-xs leading-5 text-gray-500">
              私有信源仅自己可见，抓取的内容不会出现在全局信源池中
            </p>
          </div>
          <div className="flex items-center gap-2">
            <SearchBox value={searchKeyword} onChange={setSearchKeyword} />
            <Button
              type="button"
              variant="primary"
              onClick={handleOpenCreate}
              className="min-h-9 whitespace-nowrap"
            >
              <Plus size={14} strokeWidth={2.2} />
              新建信源
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto mt-5 max-w-[860px]">
        {/* Plan upgrade banner (403 on create) */}
        {planError && (
          <NoticeBanner tone="amber" onClose={() => setPlanError(null)}>
            <strong className="font-black">当前套餐不支持创建私有信源</strong>
            <p className="mt-1 text-xs">{planError}</p>
          </NoticeBanner>
        )}

        {/* Action error banner */}
        {actionError && (
          <NoticeBanner tone="red" onClose={() => setActionError(null)}>
            <p className="text-xs">{actionError}</p>
          </NoticeBanner>
        )}

        {/* Sync result notice */}
        {lastSync && (
          <NoticeBanner tone="teal" onClose={() => setLastSync(null)}>
            <p className="text-xs">
              同步完成：抓取 {lastSync.fetched} 条，新增 {lastSync.new} 条，重复 {lastSync.duplicates} 条
            </p>
          </NoticeBanner>
        )}

        {/* Content */}
        {loading ? (
          <LoadingState label="加载中…" minHeight="160px" panel />
        ) : error ? (
          <Panel className="grid min-h-[120px] place-items-center p-6">
            <div className="flex flex-col items-center gap-2 text-center">
              <AlertTriangle size={24} className="text-gray-300" />
              <p className="text-sm text-gray-500">{error}</p>
              <Button variant="secondary" onClick={() => void refetch()} className="mt-1">
                重试
              </Button>
            </div>
          </Panel>
        ) : items.length === 0 ? (
          <EmptyState
            icon={RadioTower}
            title={searchKeyword ? `没有匹配「${searchKeyword}」的私有信源` : '还没有私有信源'}
            desc={searchKeyword ? undefined : '创建私有信源来抓取专属内容（仅你可见，不进全局池）'}
            actions={searchKeyword ? undefined : [{ label: '创建第一个私有信源', onClick: handleOpenCreate, variant: 'primary' }]}
            minHeight="180px"
          />
        ) : (
          <div className="flex flex-col gap-3">
            {items.map((source) => (
              <PrivateSourceCard
                key={source.id}
                source={source}
                syncing={syncingId === source.id}
                onEdit={() => handleEdit(source)}
                onDelete={() => handleDelete(source)}
                onSync={() => handleSync(source)}
              />
            ))}
          </div>
        )}
      </main>

      {/* Create / edit modal */}
      {showForm && (
        <SourceFormModal
          editing={editing}
          form={form}
          setForm={setForm}
          submitting={submitting}
          onSubmit={handleSubmit}
          onClose={() => {
            setShowForm(false);
            setEditing(null);
            setForm(emptyForm);
          }}
        />
      )}
    </div>
  );
}

// ─── Sub-components ───

function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
      <input
        type="text"
        placeholder="搜索名称 / URL"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-44 rounded-sm border border-gray-200 bg-white pl-8 pr-3 text-[13px] text-gray-800 outline-none transition placeholder:text-gray-300 focus:border-primary-border focus:ring-2 focus:ring-primary-light sm:w-56"
      />
    </div>
  );
}

/** 统一的横幅通知（planError / actionError / syncResult 共用） */
function NoticeBanner({
  tone,
  children,
  onClose,
}: {
  tone: 'amber' | 'red' | 'teal';
  children: React.ReactNode;
  onClose?: () => void;
}) {
  const toneClass = {
    amber: 'border-amber-border bg-amber-light text-amber',
    red: 'border-red-border bg-red-light text-red',
    teal: 'border-teal-border bg-teal-light text-teal',
  }[tone];
  return (
    <Panel className={cx('mb-4 px-4 py-3', toneClass)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">{children}</div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-sm p-0.5 opacity-60 transition hover:opacity-100"
            aria-label="关闭"
          >
            <X size={14} />
          </button>
        )}
      </div>
    </Panel>
  );
}

// ─── 类型颜色映射（与 SourceRowComponent 保持一致） ───
const TYPE_COLORS: Record<string, string> = {
  RSS: 'border-purple-border bg-purple-light text-purple',
  RSSHub: 'border-teal-border bg-teal-light text-teal',
  API: 'border-primary-border bg-primary-light text-primary',
  网站: 'border-amber-border bg-amber-light text-amber',
};

const INTERVAL_LABELS: Record<number, string> = {
  30: '30分钟',
  60: '1小时',
  120: '2小时',
  360: '6小时',
  720: '12小时',
  1440: '1天',
};

function formatInterval(minutes: number): string {
  return INTERVAL_LABELS[minutes] || `${minutes}分钟`;
}

/** 私有信源卡片 — 替代 admin 的 9 列表格行，适配窄容器 */
function PrivateSourceCard({
  source,
  syncing,
  onEdit,
  onDelete,
  onSync,
}: {
  source: BackendSource;
  syncing: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onSync: () => void;
}) {
  const typeClass = TYPE_COLORS[source.source_type] || 'border-gray-200 bg-gray-100 text-gray-600';
  const isActive = source.status === 'active' && source.enabled;
  const sourceSyncing = syncing || source.status === 'syncing';
  const sourceDisabled = !source.enabled;
  const syncDisabled = sourceSyncing || sourceDisabled;
  const weightBonus = (source.weight - 3) * 8;

  return (
    <Panel className="p-4 transition hover:border-primary-border/40">
      {/* Row 1: name + type + status */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[15px] font-black text-gray-900">{source.name}</span>
        <span className={cx('rounded border px-2 py-0.5 text-[11px] font-bold', typeClass)}>
          {source.source_type}
        </span>
        <span className="ml-auto flex items-center gap-1.5">
          <span className={cx('h-2 w-2 rounded-full', isActive ? 'bg-teal' : sourceDisabled ? 'bg-gray-300' : 'bg-red')} />
          <span className={cx('text-[11px] font-bold', isActive ? 'text-teal' : sourceDisabled ? 'text-gray-400' : 'text-red')}>
            {sourceDisabled ? '已禁用' : sourceSyncing ? '同步中' : source.status === 'active' ? '正常' : source.status}
          </span>
        </span>
      </div>

      {/* Row 2: url */}
      {source.url && (
        <div className="mt-1.5 truncate font-mono text-[11px] text-gray-400" title={source.url}>
          {source.url}
        </div>
      )}

      {/* Row 3: meta tags */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-gray-500">
        <span className="flex items-center gap-1">
          <span className="text-gray-400">分类</span>
          <span className="font-bold text-gray-700">{source.category || '未分类'}</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="text-gray-400">频率</span>
          <span className="font-bold text-gray-700">{formatInterval(source.fetch_interval_minutes)}</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="text-gray-400">权重</span>
          <span className="flex items-center gap-0.5">
            {[1, 2, 3, 4, 5].map((w) => (
              <span key={w} className={cx('text-[11px]', w <= source.weight ? 'text-primary' : 'text-gray-200')}>●</span>
            ))}
          </span>
          {weightBonus !== 0 && (
            <span className={cx('ml-1 font-mono text-[10px]', weightBonus > 0 ? 'text-teal' : 'text-gray-400')}>
              {weightBonus > 0 ? `+${weightBonus}` : weightBonus}
            </span>
          )}
        </span>
        <span className="flex items-center gap-1">
          <span className="text-gray-400">同步</span>
          <span className={cx('font-bold', source.sync_error ? 'text-red' : 'text-gray-700')}>
            {sourceSyncing ? '同步中…' : source.sync_error ? '失败' : timeAgo(source.last_sync_at)}
          </span>
        </span>
      </div>

      {/* Sync error detail */}
      {source.sync_error && (
        <div className="mt-2 rounded-xs bg-red-light px-2.5 py-1.5 text-[11px] text-red">
          {source.sync_error}
        </div>
      )}

      {/* Row 4: actions */}
      <div className="mt-3.5 flex items-center gap-2 border-t border-gray-100 pt-3">
        <Button
          type="button"
          onClick={onSync}
          disabled={syncDisabled}
          variant={sourceSyncing ? 'secondary' : 'success'}
          className="min-h-0 px-3 py-1.5 text-[12px]"
          title={sourceDisabled ? '信源已禁用，启用后可同步' : '同步信源'}
        >
          {sourceSyncing ? <Loader2 size={13} className="animate-spin" /> : null}
          {sourceSyncing ? '同步中' : '同步'}
        </Button>
        <Button
          type="button"
          onClick={onEdit}
          variant="secondary"
          className="min-h-0 px-3 py-1.5 text-[12px]"
        >
          编辑
        </Button>
        <Button
          type="button"
          onClick={onDelete}
          variant="ghost"
          className="min-h-0 px-3 py-1.5 text-[12px] text-red hover:bg-red-light hover:text-red"
        >
          删除
        </Button>
      </div>
    </Panel>
  );
}

// ─── Form Modal ───

function SourceFormModal({
  editing,
  form,
  setForm,
  submitting,
  onSubmit,
  onClose,
}: {
  editing: BackendSource | null;
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  submitting: boolean;
  onSubmit: () => void;
  onClose: () => void;
}) {
  const mode: FormMode = editing ? 'edit' : 'create';
  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 px-4"
      onClick={onClose}
    >
      <Panel onClick={(e) => e.stopPropagation()} className="w-full max-w-[480px] p-8 shadow-2xl">
        <h2 className="mb-6 text-xl font-black text-gray-900">
          {mode === 'create' ? '新建私有信源' : `编辑：${editing?.name ?? ''}`}
        </h2>
        <SourceForm form={form} setForm={setForm} />
        <div className="mt-7 flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose} disabled={submitting} className="px-5">
            取消
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={onSubmit}
            disabled={submitting || !form.name.trim()}
            className="px-5"
          >
            {submitting ? (mode === 'create' ? '创建中…' : '保存中…') : (mode === 'create' ? '创建' : '保存')}
          </Button>
        </div>
      </Panel>
    </div>
  );
}
