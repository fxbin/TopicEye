'use client';

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Activity, FileSearch, List, Network, Plus, Star, Upload } from 'lucide-react';
import { favoritesApi, sourcesApi, settingsApi } from '@/lib/api';
import type { RSSHubInstance, CreateSourceRequest, SourceBatchImportItem, UpdateSourceRequest } from '@/lib/api';
import { useAppContext } from '@/components/ClientLayout';
import { timeAgo } from '@/lib/utils';
import { Badge, Button, Panel, Toolbar, cx } from '@/components/ui';
import SourceForm, { FormState, emptyForm } from '@/components/SourceForm';
import SourceRowComponent, { type BackendSource } from '@/components/SourceRow';
import { Spinner } from '@/components/SourceRow';
import SourceSyncBoard from '@/components/SourceSyncBoard';
import { buildSourceSyncBoard, sourceTypeLabel } from '@/lib/source-sync-board';
import { getFavoriteTargetKey } from '@/lib/favorites';

// ─── Page Component ───

type SourceTierKey = 'core' | 'stable' | 'watch' | 'attention';
type DropTarget = { tier: SourceTierKey; beforeId: number | null };

const sourceTierMeta: Record<SourceTierKey, { label: string; desc: string; text: string; bg: string; border: string; dot: string; tone: 'primary' | 'teal' | 'amber' | 'red' }> = {
  core: { label: '核心信源', desc: '高权重、正常采集，影响精选排序', text: 'text-primary', bg: 'bg-primary-light', border: 'border-primary-border', dot: 'bg-primary', tone: 'primary' },
  stable: { label: '稳定信源', desc: '常规权重，作为日常覆盖面', text: 'text-teal', bg: 'bg-teal-light', border: 'border-teal-border', dot: 'bg-teal', tone: 'teal' },
  watch: { label: '观察池', desc: '低权重或新来源，先保留信号', text: 'text-amber', bg: 'bg-amber-light', border: 'border-amber-border', dot: 'bg-amber', tone: 'amber' },
  attention: { label: '待处理', desc: '禁用、报错或同步异常', text: 'text-red', bg: 'bg-red-light', border: 'border-red-light', dot: 'bg-red', tone: 'red' },
};

function getSourceTier(source: BackendSource): SourceTierKey {
  if (source.status === 'syncing') return 'stable';
  if (!source.enabled || source.status === 'error' || source.sync_error) return 'attention';
  if ((source.weight ?? 3) >= 4) return 'core';
  if ((source.weight ?? 3) <= 2) return 'watch';
  return 'stable';
}

function normalizeRsshubInstanceUrl(value: string): string | null {
  try {
    const url = new URL(value.trim());
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    url.protocol = url.protocol.toLowerCase();
    url.hostname = url.hostname.toLowerCase();
    url.pathname = url.pathname.replace(/\/+$/, '');
    url.search = '';
    url.hash = '';
    return url.toString().replace(/\/$/, '');
  } catch {
    return null;
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function validateApiSourceConfig(form: FormState): string | null {
  if (form.source_type !== 'API' || !form.keyword.trim()) return null;

  let config: unknown;
  try {
    config = JSON.parse(form.keyword);
  } catch {
    return 'API 配置必须是合法 JSON 对象';
  }

  if (!isPlainObject(config)) return 'API 配置必须是合法 JSON 对象';

  const method = config.method;
  if (method !== undefined && (typeof method !== 'string' || !['GET', 'POST'].includes(method.trim().toUpperCase()))) {
    return 'API 配置 method 仅支持 GET 或 POST';
  }

  for (const key of ['headers', 'params', 'body', 'fields']) {
    const value = config[key];
    if (value !== undefined && value !== null && !isPlainObject(value)) {
      return `API 配置 ${key} 必须是 JSON 对象`;
    }
  }

  const itemsPath = config.items_path;
  if (itemsPath !== undefined && (typeof itemsPath !== 'string' || !itemsPath.trim())) {
    return 'API 配置 items_path 必须是非空字符串';
  }

  const timeout = config.timeout;
  if (timeout !== undefined) {
    const value = Number(timeout);
    if (!Number.isFinite(value) || value < 1 || value > 120) {
      return 'API 配置 timeout 必须是 1 到 120 秒之间的数字';
    }
  }

  return null;
}

function SourceMapView({
  sourceMap,
  syncingIds,
  favoriteTargets,
  favoriteTargetPendingKeys,
  onEdit,
  onSync,
  onToggleEnabled,
  onFavorite,
  onMove,
}: {
  sourceMap: {
    tiers: Record<SourceTierKey, BackendSource[]>;
    categories: [string, number][];
    types: [string, number][];
    attentionCount: number;
    coreCount: number;
  };
  syncingIds: Set<number>;
  favoriteTargets: Set<string>;
  favoriteTargetPendingKeys: Set<string>;
  onEdit: (source: BackendSource) => void;
  onSync: (id: number) => void;
  onToggleEnabled: (source: BackendSource) => void;
  onFavorite: (source: BackendSource) => void;
  onMove: (source: BackendSource, targetTier: SourceTierKey, orderedIds: number[]) => void;
}) {
  const tierKeys: SourceTierKey[] = ['core', 'stable', 'watch', 'attention'];
  const [draggedId, setDraggedId] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);

  const handleDrop = (targetTier: SourceTierKey, beforeId: number | null) => {
    if (!draggedId) return;
    const allSources = Object.values(sourceMap.tiers).flatMap((items) => items);
    const draggedSource = allSources.find((item) => item.id === draggedId);
    if (!draggedSource) return;

    const targetItems = sourceMap.tiers[targetTier].filter((item) => item.id !== draggedId);
    const beforeIndex = beforeId === null ? -1 : targetItems.findIndex((item) => item.id === beforeId);
    const nextItems = [...targetItems];
    if (beforeIndex >= 0) {
      nextItems.splice(beforeIndex, 0, draggedSource);
    } else {
      nextItems.push(draggedSource);
    }

    onMove(draggedSource, targetTier, nextItems.map((item) => item.id));
    setDropTarget(null);
    setDraggedId(null);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel className="p-4.5">
          <div className="mb-3.5 flex items-center gap-2">
            <Network size={18} className="text-primary" strokeWidth={2} />
            <h2 className="m-0 text-[15px] font-black text-gray-800">等级分布</h2>
          </div>
          <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">
            {tierKeys.map((key) => {
              const meta = sourceTierMeta[key];
              return (
                <div key={key} className={cx('rounded-sm border p-3', meta.bg, meta.border)}>
                  <div className={cx('mb-1.5 text-[11px] font-black', meta.text)}>{meta.label}</div>
                  <div className="font-mono text-2xl font-black leading-none text-gray-900">{sourceMap.tiers[key].length}</div>
                  <div className="mt-1.5 text-[11px] leading-5 text-gray-500">{meta.desc}</div>
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel className="p-4.5">
          <h2 className="mb-3.5 text-[15px] font-black text-gray-800">分类与类型</h2>
          <div className="mb-3.5 flex flex-wrap gap-2">
            {sourceMap.categories.map(([name, count]) => (
              <Badge key={name} tone="neutral" className="font-semibold">
                {name} <b className="ml-1 font-mono text-gray-900">{count}</b>
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {sourceMap.types.map(([name, count]) => (
              <Badge key={name} tone="teal">
                {name} · {count}
              </Badge>
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 items-start gap-3 md:grid-cols-2 2xl:grid-cols-4">
        {tierKeys.map((key) => {
          const meta = sourceTierMeta[key];
          const isDragOver = dropTarget?.tier === key;
          return (
            <section
              key={key}
              data-source-tier={key}
              className="flex h-[clamp(420px,calc(100vh-300px),760px)] min-w-0 flex-col"
            >
              <div className="mb-2 flex shrink-0 items-center justify-between gap-3 px-0.5">
                <h3 className={cx('m-0 text-[13px] font-black', meta.text)}>{meta.label}</h3>
                <span className="font-mono text-[11px] text-gray-400">{sourceMap.tiers[key].length} 条</span>
              </div>
              <div
                className={cx(
                  'source-map-column-scroll flex min-h-44 flex-col gap-2 overflow-y-auto overscroll-contain rounded-sm border border-dashed p-2 pr-1 transition',
                  isDragOver ? `${meta.bg} ${meta.border}` : 'border-transparent bg-transparent',
                )}
                onDragOver={(event) => {
                  event.preventDefault();
                  if (dropTarget?.tier !== key || dropTarget.beforeId !== null) {
                    setDropTarget({ tier: key, beforeId: null });
                  }
                }}
                onDragLeave={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                    setDropTarget(null);
                  }
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  handleDrop(key, null);
                }}
              >
                {sourceMap.tiers[key].map((source) => (
                  <SourceMapCard
                    key={source.id}
                    source={source}
                    tierKey={key}
                    syncing={syncingIds.has(source.id)}
                    favoriteTargets={favoriteTargets}
                    favoriteTargetPendingKeys={favoriteTargetPendingKeys}
                    draggedId={draggedId}
                    dropTarget={dropTarget}
                    onEdit={onEdit}
                    onSync={onSync}
                    onToggleEnabled={onToggleEnabled}
                    onFavorite={onFavorite}
                    onDragOver={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      if (draggedId !== source.id) {
                        setDropTarget({ tier: key, beforeId: source.id });
                      }
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      handleDrop(key, source.id);
                    }}
                    onDragStart={(event) => {
                      event.dataTransfer.setData('text/plain', String(source.id));
                      event.dataTransfer.effectAllowed = 'move';
                      setDraggedId(source.id);
                    }}
                    onDragEnd={() => {
                      setDraggedId(null);
                      setDropTarget(null);
                    }}
                  />
                ))}
                {sourceMap.tiers[key].length === 0 && (
                  <div className="rounded-sm border border-dashed border-gray-200 bg-gray-50 p-4 text-center text-xs text-gray-400">暂无信源</div>
                )}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

function SourceMapCard({
  source,
  tierKey,
  syncing,
  favoriteTargets,
  favoriteTargetPendingKeys,
  draggedId,
  dropTarget,
  onEdit,
  onSync,
  onToggleEnabled,
  onFavorite,
  onDragOver,
  onDrop,
  onDragStart,
  onDragEnd,
}: {
  source: BackendSource;
  tierKey: SourceTierKey;
  syncing: boolean;
  favoriteTargets: Set<string>;
  favoriteTargetPendingKeys: Set<string>;
  draggedId: number | null;
  dropTarget: DropTarget | null;
  onEdit: (source: BackendSource) => void;
  onSync: (id: number) => void;
  onToggleEnabled: (source: BackendSource) => void;
  onFavorite: (source: BackendSource) => void;
  onDragOver: React.DragEventHandler<HTMLDivElement>;
  onDrop: React.DragEventHandler<HTMLDivElement>;
  onDragStart: React.DragEventHandler<HTMLDivElement>;
  onDragEnd: React.DragEventHandler<HTMLDivElement>;
}) {
  const favoriteKey = getFavoriteTargetKey({ target_type: 'source', target_id: source.id });
  const isFavorite = favoriteTargets.has(favoriteKey);
  const favoritePending = favoriteTargetPendingKeys.has(favoriteKey);
  const meta = sourceTierMeta[tierKey];
  const sourceSyncing = syncing || source.status === 'syncing';
  const sourceDisabled = !source.enabled || source.status === 'disabled';
  const syncDisabled = sourceSyncing || sourceDisabled;

  return (
    <div
      data-source-map-card-id={source.id}
      data-source-map-card-name={source.name}
      data-source-map-card-tier={tierKey}
      draggable
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={cx(
        'cursor-grab rounded-sm border bg-white p-3 transition',
        source.sync_error ? 'border-red-light' : 'border-gray-200',
        draggedId === source.id && 'opacity-50 shadow-lg',
        dropTarget?.tier === tierKey && dropTarget.beforeId === source.id && `border-t-4 ${meta.border}`,
      )}
      title="拖动到其他分组可调整信源等级"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-black text-gray-800">{source.name}</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">{sourceTypeLabel(source.source_type)}</span>
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">{source.category || '未分类'}</span>
            <span className="rounded bg-primary-light px-1.5 py-0.5 text-[10px] text-primary">权重 {source.weight ?? 3}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            disabled={favoritePending}
            onClick={(event) => {
              event.stopPropagation();
              onFavorite(source);
            }}
            className={cx(
              'flex h-7 w-7 items-center justify-center rounded-sm border transition disabled:cursor-wait disabled:opacity-60',
              isFavorite ? 'border-amber-border bg-amber-light text-amber' : 'border-gray-200 bg-white text-gray-300 hover:text-amber',
            )}
            title={isFavorite ? '移出收藏' : '收藏信源'}
          >
            <Star size={13} fill={isFavorite ? 'currentColor' : 'none'} />
          </button>
          <span className={cx('h-2 w-2 rounded-full', sourceTierMeta[getSourceTier(source)].dot)} />
        </div>
      </div>
      <div className={cx('mt-2 text-[11px] leading-5', source.sync_error ? 'text-red' : 'text-gray-400')}>
        {sourceSyncing ? '同步中' : source.sync_error ? source.sync_error : `最近同步 ${timeAgo(source.last_sync_at)}`}
      </div>
      <div className="mt-2.5 flex gap-1.5">
        <Button
          type="button"
          variant="success"
          onClick={() => onSync(source.id)}
          disabled={syncDisabled}
          className="min-h-7 flex-1 px-2 py-1 text-[11px]"
          title={sourceDisabled ? '信源已禁用，启用后可同步' : '同步信源'}
        >
          {sourceSyncing ? '同步中' : '同步'}
        </Button>
        <Button type="button" variant="secondary" onClick={() => onEdit(source)} className="min-h-7 flex-1 px-2 py-1 text-[11px]">
          编辑
        </Button>
        <Button
          type="button"
          variant={source.enabled ? 'secondary' : 'primary'}
          onClick={() => onToggleEnabled(source)}
          disabled={sourceSyncing}
          className="min-h-7 px-2 py-1 text-[11px]"
          title={source.enabled ? '暂停此信源抓取' : '启用此信源抓取'}
        >
          {source.enabled ? '暂停' : '启用'}
        </Button>
      </div>
    </div>
  );
}

export default function SourcesPage() {
  const { favoriteTargets, favoriteTargetPendingKeys, toggleFavoriteTarget, refreshCounts } = useAppContext();
  const [sources, setSources] = useState<BackendSource[]>([]);
  const [mapSources, setMapSources] = useState<BackendSource[]>([]);
  const [sourceFavoriteKeys, setSourceFavoriteKeys] = useState<Set<string>>(new Set());
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [viewMode, setViewMode] = useState<'map' | 'sync' | 'list'>('map');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterEnabled, setFilterEnabled] = useState<boolean | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingSource, setEditingSource] = useState<BackendSource | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [syncingIds, setSyncingIds] = useState<Set<number>>(new Set());
  const [syncResults, setSyncResults] = useState<Record<number, string>>({});
  const [deletingIds, setDeletingIds] = useState<Set<number>>(new Set());
  const [rsshubInstances, setRsshubInstances] = useState<RSSHubInstance[]>([]);
  const [rsshubLoading, setRsshubLoading] = useState(true);
  const [rsshubSaving, setRsshubSaving] = useState(false);
  const [rsshubError, setRsshubError] = useState<string | null>(null);
  const [newInstanceUrl, setNewInstanceUrl] = useState('');
  const opmlInputRef = useRef<HTMLInputElement>(null);
  const batchImportInputRef = useRef<HTMLInputElement>(null);
  const [, setImportingOPML] = useState(false);
  const [showBatchImport, setShowBatchImport] = useState(false);
  const [batchImportContent, setBatchImportContent] = useState('');
  const [batchImportCategory, setBatchImportCategory] = useState('批量导入');
  const [batchImportPreview, setBatchImportPreview] = useState<SourceBatchImportItem[]>([]);
  const [batchImportPreviewing, setBatchImportPreviewing] = useState(false);
  const [batchImporting, setBatchImporting] = useState(false);

  // ─── Fetch sources ───
  const fetchSources = useCallback(async (p: number = 1): Promise<boolean> => {
    try {
      setLoading(true);
      setError(null);
      const res = await sourcesApi.list({
        page: p,
        page_size: pageSize,
        source_type: filterType || undefined,
        enabled: filterEnabled,
        keyword: searchKeyword || undefined,
      });
      const items = res?.items || [];
      setSources(items as BackendSource[]);
      setTotal(res?.total ?? 0);
      setPage(p);
      return true;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载信源列表失败');
      return false;
    } finally {
      setLoading(false);
    }
  }, [pageSize, filterType, filterEnabled, searchKeyword]);

  const fetchSourceMap = useCallback(async (): Promise<boolean> => {
    try {
      const pageSizeForMap = 100;
      const firstPage = await sourcesApi.list({
        page: 1,
        page_size: pageSizeForMap,
        source_type: filterType || undefined,
        enabled: filterEnabled,
        keyword: searchKeyword || undefined,
      });
      const allItems = [...((firstPage?.items || []) as BackendSource[])];
      const totalItems = firstPage?.total ?? allItems.length;
      const totalPages = Math.ceil(totalItems / pageSizeForMap);

      if (totalPages > 1) {
        const rest = await Promise.all(
          Array.from({ length: totalPages - 1 }, (_, idx) =>
            sourcesApi.list({
              page: idx + 2,
              page_size: pageSizeForMap,
              source_type: filterType || undefined,
              enabled: filterEnabled,
              keyword: searchKeyword || undefined,
            })
          )
        );
        rest.forEach((res) => allItems.push(...((res?.items || []) as BackendSource[])));
      }

      setMapSources(allItems);
      return true;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载信源地图失败');
      return false;
    }
  }, [filterType, filterEnabled, searchKeyword]);

  // ─── Fetch RSSHub instances ───
  const fetchRSSHubInstances = useCallback(async () => {
    try {
      setRsshubLoading(true);
      const data = await settingsApi.getRSSHubInstances();
      setRsshubInstances(data.instances || []);
    } catch (err: unknown) {
      setRsshubError(err instanceof Error ? err.message : '加载RSSHub实例失败');
    } finally {
      setRsshubLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSources(1);
    fetchSourceMap();
    fetchRSSHubInstances();
  }, [fetchSources, fetchSourceMap, fetchRSSHubInstances]);

  useEffect(() => {
    const ids = Array.from(new Set([...sources, ...mapSources].map((source) => source.id)));
    if (ids.length === 0) {
      setSourceFavoriteKeys(new Set());
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const state = await favoritesApi.state({
          target_type: 'source',
          target_ids: ids,
        });
        if (cancelled) return;
        const favoriteIds = new Set(
          (state.items || [])
            .filter((item) => item.is_favorited)
            .map((item) => Number(item.target_key))
            .filter((id) => Number.isFinite(id)),
        );
        setSourceFavoriteKeys(new Set(ids.filter((id) => favoriteIds.has(id)).map((id) => getFavoriteTargetKey({ target_type: 'source', target_id: id }))));
      } catch {
        if (!cancelled) setSourceFavoriteKeys(new Set());
      }
    })();

    return () => { cancelled = true; };
  }, [sources, mapSources]);

  // ─── Toggle instance enabled ───
  const toggleInstance = async (url: string) => {
    const updated = rsshubInstances.map((i) =>
      i.url === url ? { ...i, enabled: !i.enabled } : i
    );
    setRsshubInstances(updated);
    try {
      setRsshubSaving(true);
      await settingsApi.updateRSSHubInstances(updated);
    } catch (err: unknown) {
      setRsshubError(err instanceof Error ? err.message : '更新失败');
      setRsshubInstances((prev) => prev.map((i) => i.url === url ? { ...i, enabled: !i.enabled } : i));
    } finally {
      setRsshubSaving(false);
    }
  };

  // ─── Add instance ───
  const addInstance = async () => {
    const url = normalizeRsshubInstanceUrl(newInstanceUrl);
    if (!url) {
      setRsshubError('请输入以 http/https 开头的有效 URL');
      return;
    }
    if (rsshubInstances.find((i) => normalizeRsshubInstanceUrl(i.url) === url)) {
      setRsshubError('该实例已存在');
      return;
    }
    const updated = [...rsshubInstances, { url, enabled: true, priority: rsshubInstances.length, note: '' }];
    setRsshubInstances(updated);
    setNewInstanceUrl('');
    try {
      setRsshubSaving(true);
      await settingsApi.updateRSSHubInstances(updated);
    } catch (err: unknown) {
      setRsshubError(err instanceof Error ? err.message : '添加失败');
      setRsshubInstances((prev) => prev.filter((i) => i.url !== url));
    } finally {
      setRsshubSaving(false);
    }
  };

  // ─── Delete instance ───
  const deleteInstance = async (url: string) => {
    if (!confirm(`删除实例 ${url}？`)) return;
    const prev = rsshubInstances;
    setRsshubInstances((prev) => prev.filter((i) => i.url !== url));
    try {
      setRsshubSaving(true);
      await settingsApi.updateRSSHubInstances(rsshubInstances.filter((i) => i.url !== url));
    } catch (err: unknown) {
      setRsshubError(err instanceof Error ? err.message : '删除失败');
      setRsshubInstances(prev);
    } finally {
      setRsshubSaving(false);
    }
  };

  // ─── Create source ───
  const handleCreate = async () => {
    if (!form.name.trim()) return;
    const configError = validateApiSourceConfig(form);
    if (configError) {
      setError(configError);
      return;
    }
    try {
      setSubmitting(true);
      await sourcesApi.create({
        name: form.name.trim(),
        source_type: form.source_type,
        url: form.url.trim(),
        keyword: form.keyword.trim() || null,
        category: form.category,
        weight: form.weight,
        fetch_interval_minutes: form.fetch_interval_minutes,
        enabled: form.enabled,
      } as CreateSourceRequest);
      setShowAddModal(false);
      setForm(emptyForm);
      await fetchSources();
      await fetchSourceMap();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '添加信源失败');
    } finally {
      setSubmitting(false);
    }
  };

  // ─── Import OPML ───
  const handleOPMLImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportingOPML(true);
    try {
      const result = await sourcesApi.importOPML(file);
      // Show success as a temporary rsshubError display (reuses existing banner)
      setRsshubError(result.message);
      fetchSources();
      fetchSourceMap();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'OPML 导入失败');
    } finally {
      setImportingOPML(false);
      if (opmlInputRef.current) opmlInputRef.current.value = '';
    }
  };

  const handleBatchImportFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setBatchImportContent(await file.text());
    setBatchImportPreview([]);
    if (batchImportInputRef.current) batchImportInputRef.current.value = '';
  };

  const handleBatchImportPreview = async () => {
    if (!batchImportContent.trim()) {
      setError('请先粘贴信源配置或上传文件');
      return;
    }
    setBatchImportPreviewing(true);
    setError(null);
    try {
      const result = await sourcesApi.previewBatchSources({
        content: batchImportContent,
        category: batchImportCategory || '批量导入',
      });
      setBatchImportPreview(result.items || []);
      if ((result.items || []).length === 0) {
        setError('没有识别到可导入的 URL 或 RSS 配置');
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '批量导入预览失败');
    } finally {
      setBatchImportPreviewing(false);
    }
  };

  const handleBatchImport = async () => {
    if (!batchImportContent.trim()) return;
    setBatchImporting(true);
    setError(null);
    try {
      const result = await sourcesApi.importBatchSources({
        content: batchImportContent,
        category: batchImportCategory || '批量导入',
      });
      setRsshubError(result.message);
      setShowBatchImport(false);
      setBatchImportContent('');
      setBatchImportPreview([]);
      await fetchSources();
      await fetchSourceMap();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '批量导入失败');
    } finally {
      setBatchImporting(false);
    }
  };

  // ─── Update source ───
  const handleUpdate = async () => {
    if (!editingSource || !form.name.trim()) return;
    const configError = validateApiSourceConfig(form);
    if (configError) {
      setError(configError);
      return;
    }
    try {
      setSubmitting(true);
      await sourcesApi.update(editingSource.id, {
        name: form.name.trim(),
        source_type: form.source_type,
        url: form.url.trim(),
        keyword: form.keyword.trim() || null,
        category: form.category,
        weight: form.weight,
        fetch_interval_minutes: form.fetch_interval_minutes,
        enabled: form.enabled,
      } as UpdateSourceRequest);
      setEditingSource(null);
      setForm(emptyForm);
      await fetchSources();
      await fetchSourceMap();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '更新信源失败');
    } finally {
      setSubmitting(false);
    }
  };

  // ─── Open edit modal ───
  const openEditModal = (src: BackendSource) => {
    setEditingSource(src);
    setForm({
      name: src.name,
      source_type: src.source_type,
      url: src.url,
      keyword: src.keyword || '',
      category: src.category,
      weight: src.weight ?? 3,
      fetch_interval_minutes: src.fetch_interval_minutes || 60,
      enabled: src.enabled,
    });
  };

  // ─── Sync source ───
  const handleSync = async (id: number) => {
    try {
      setSyncingIds((prev) => new Set(prev).add(id));
      setSyncResults((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      const res = await sourcesApi.sync(id);
      const fetched = res?.fetched ?? 0;
      const newCount = res?.new ?? 0;
      setSyncResults((prev) => ({
        ...prev,
        [id]: `获取 ${fetched} 条，新增 ${newCount} 条`,
      }));
      await fetchSources();
      await fetchSourceMap();
    } catch (err: unknown) {
      setSyncResults((prev) => ({
        ...prev,
        [id]: `同步失败: ${err instanceof Error ? err.message : String(err)}`,
      }));
    } finally {
      setSyncingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  // ─── Toggle source enabled (soft pause / resume) ───
  const [togglingIds, setTogglingIds] = useState<Set<number>>(new Set());

  // Status-filtered sourceMap（client-side 过滤；后端不分页所以全量返回）
  const filteredSourceMap = useMemo(() => {
    if (statusFilter === 'all') return sourceMap;
    const filteredTiers = Object.fromEntries(
      Object.entries(sourceMap.tiers).map(([tier, items]) => {
        const matched = items.filter((s) => {
          if (statusFilter === 'active') return s.status === 'active' && s.enabled;
          if (statusFilter === 'syncing') return s.status === 'syncing';
          if (statusFilter === 'error') return s.status === 'error' || (s.enabled && s.sync_error);
          if (statusFilter === 'disabled') return !s.enabled || s.status === 'disabled';
          return true;
        });
        return [tier, matched];
      })
    );
    return {
      ...sourceMap,
      tiers: filteredTiers as Record<SourceTierKey, BackendSource[]>,
    };
  }, [sourceMap, statusFilter]);
  // 批量选择：多选 + 批量启用/暂停
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchProcessing, setBatchProcessing] = useState(false);
  // 状态筛选（按 source.status + enabled 状态过滤）
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'syncing' | 'error' | 'disabled'>('all');
  const handleSelectSource = (source: BackendSource, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(source.id);
      else next.delete(source.id);
      return next;
    });
  };
  const handleSelectAllVisible = (sources: BackendSource[], checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) sources.forEach((s) => next.add(s.id));
      else sources.forEach((s) => next.delete(s.id));
      return next;
    });
  };
  const handleBatchToggle = async (enabled: boolean) => {
    if (selectedIds.size === 0 || batchProcessing) return;
    setBatchProcessing(true);
    try {
      // 循环调 update 端点（已存在，单 source 调）
      const ids = Array.from(selectedIds);
      for (const id of ids) {
        try {
          await sourcesApi.update(id, { enabled });
        } catch (err) {
          console.error(`Batch toggle source ${id} failed:`, err);
        }
      }
      setSelectedIds(new Set());
      await fetchSources();
      await fetchSourceMap();
    } finally {
      setBatchProcessing(false);
    }
  };
  const handleToggleEnabled = async (source: BackendSource) => {
    if (togglingIds.has(source.id)) return;
    const nextEnabled = !source.enabled;
    try {
      setTogglingIds((prev) => new Set(prev).add(source.id));
      await sourcesApi.update(source.id, { enabled: nextEnabled });
      await fetchSources();
      await fetchSourceMap();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setTogglingIds((prev) => {
        const next = new Set(prev);
        next.delete(source.id);
        return next;
      });
    }
  };

  // ─── Delete source ───
  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除此信源吗？')) return;
    try {
      setDeletingIds((prev) => new Set(prev).add(id));
      await sourcesApi.delete(id);
      setSources((prev) => prev.filter((s) => s.id !== id));
      setMapSources((prev) => prev.filter((s) => s.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const handleWeightChange = async (id: number, weight: number) => {
    try {
      await sourcesApi.update(id, { weight });
      setSources((prev) => prev.map((s) => (s.id === id ? { ...s, weight } : s)));
      setMapSources((prev) => prev.map((s) => (s.id === id ? { ...s, weight } : s)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '权重更新失败');
    }
  };

  const handleIntervalChange = async (id: number, fetch_interval_minutes: number) => {
    try {
      await sourcesApi.update(id, { fetch_interval_minutes });
      setSources((prev) => prev.map((s) => (s.id === id ? { ...s, fetch_interval_minutes } : s)));
      setMapSources((prev) => prev.map((s) => (s.id === id ? { ...s, fetch_interval_minutes } : s)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '采集频率更新失败');
    }
  };

  const handleMoveSourceTier = async (source: BackendSource, targetTier: SourceTierKey, orderedIds: number[]) => {
    const currentTier = getSourceTier(source);
    const orderLookup = new Map(orderedIds.map((id, index) => [id, (index + 1) * 10]));

    const patchByTier: Record<SourceTierKey, UpdateSourceRequest> = {
      core: { weight: 5, enabled: true, status: 'active', sync_error: null },
      stable: { weight: 3, enabled: true, status: 'active', sync_error: null },
      watch: { weight: 1, enabled: true, status: 'active', sync_error: null },
      attention: { enabled: false, status: 'disabled' },
    };
    const patch = currentTier === targetTier ? {} : patchByTier[targetTier];
    const applyPatch = (item: BackendSource) => {
      const sort_order = orderLookup.get(item.id);
      const tierPatch = item.id === source.id ? patch : {};
      return sort_order !== undefined || item.id === source.id
        ? { ...item, ...tierPatch, ...(sort_order !== undefined ? { sort_order } : {}) }
        : item;
    };
    const previousSources = sources;
    const previousMapSources = mapSources;

    setSources((prev) => prev.map(applyPatch));
    setMapSources((prev) => prev.map(applyPatch));

    try {
      if (currentTier !== targetTier) {
        await sourcesApi.update(source.id, patch);
      }
      await sourcesApi.reorder(orderedIds);
      await fetchSources(page);
      await fetchSourceMap();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '移动信源分组失败';
      const [listRestored, mapRestored] = await Promise.all([
        fetchSources(page),
        fetchSourceMap(),
      ]);
      if (listRestored || mapRestored) {
        setError(`${message}，已恢复服务器状态`);
      } else {
        setSources(previousSources);
        setMapSources(previousMapSources);
        setError(`${message}，恢复服务器状态失败，请手动刷新`);
      }
    }
  };

  const handleToggleSourceFavorite = async (source: BackendSource) => {
    const favoriteKey = getFavoriteTargetKey({ target_type: 'source', target_id: source.id });
    const isFavorited = favoriteTargets.has(favoriteKey) || sourceFavoriteKeys.has(favoriteKey);
    const payload = {
      target_type: 'source' as const,
      target_id: source.id,
      title: source.name,
      url: source.url,
      source_name: source.name,
      snapshot: {
        source_type: source.source_type,
        category: source.category,
        status: source.status,
        enabled: source.enabled,
        weight: source.weight,
        last_sync_at: source.last_sync_at,
      },
    };

    try {
      if (isFavorited && favoriteTargets.has(favoriteKey)) {
        const nextFavorited = await toggleFavoriteTarget(payload, { throwOnError: true });
        setSourceFavoriteKeys((prev) => {
          const next = new Set(prev);
          if (nextFavorited) {
            next.add(favoriteKey);
          } else {
            next.delete(favoriteKey);
          }
          return next;
        });
        return;
      }

      if (isFavorited) {
        const state = await favoritesApi.state({ target_type: 'source', target_ids: [source.id] });
        const favoriteId = state.items.find((item) => item.is_favorited)?.favorite_id;
        if (!favoriteId) {
          throw new Error('收藏记录不存在，请刷新后重试');
        }
        await favoritesApi.delete(favoriteId);
        setSourceFavoriteKeys((prev) => {
          const next = new Set(prev);
          next.delete(favoriteKey);
          return next;
        });
        refreshCounts();
        return;
      }

      const nextFavorited = await toggleFavoriteTarget(payload, { throwOnError: true });
      setSourceFavoriteKeys((prev) => {
        const next = new Set(prev);
        if (nextFavorited) {
          next.add(favoriteKey);
        } else {
          next.delete(favoriteKey);
        }
        return next;
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '收藏信源失败');
    }
  };

  // ─── Stats ───
  const activeCount = sources.filter((s) => s.status === 'active' && s.enabled).length;
  const sourceMap = useMemo(() => {
    const tiers: Record<SourceTierKey, BackendSource[]> = {
      core: [],
      stable: [],
      watch: [],
      attention: [],
    };
    const categoryCount = new Map<string, number>();
    const typeCount = new Map<string, number>();

    mapSources.forEach((source) => {
      tiers[getSourceTier(source)].push(source);
      categoryCount.set(source.category || '未分类', (categoryCount.get(source.category || '未分类') || 0) + 1);
      typeCount.set(sourceTypeLabel(source.source_type), (typeCount.get(sourceTypeLabel(source.source_type)) || 0) + 1);
    });

    const sortEntries = (entries: [string, number][]) => entries.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    Object.values(tiers).forEach((items) => {
      items.sort((a, b) => {
        const orderDiff = (a.sort_order ?? a.id * 10) - (b.sort_order ?? b.id * 10);
        if (orderDiff !== 0) return orderDiff;
        return a.name.localeCompare(b.name);
      });
    });

    return {
      tiers,
      categories: sortEntries([...categoryCount.entries()]),
      types: sortEntries([...typeCount.entries()]),
      attentionCount: tiers.attention.length,
      coreCount: tiers.core.length,
    };
  }, [mapSources]);

  const syncBoard = useMemo(() => buildSourceSyncBoard(mapSources, syncingIds, new Date()), [mapSources, syncingIds]);

  return (
    <div className="fade-in h-full overflow-y-auto px-10 py-8">
      {/* Header */}
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {selectedIds.size > 0 && (
              <div className="flex items-center gap-1.5 rounded-sm border border-orange/30 bg-orange/5 px-2.5 py-1 text-[12px]">
                <span className="font-mono font-semibold text-orange">{selectedIds.size}</span>
                <span className="text-gray-600">已选</span>
                <button
                  type="button"
                  onClick={() => setSelectedIds(new Set())}
                  className="ml-1 text-[11px] text-gray-500 hover:text-gray-700"
                >
                  清除
                </button>
                <span className="mx-1 h-3 w-px bg-gray-300" />
                <button
                  type="button"
                  onClick={() => void handleBatchToggle(true)}
                  disabled={batchProcessing}
                  className="text-[12px] text-teal hover:underline disabled:opacity-50"
                >
                  批量启用
                </button>
                <span className="text-gray-300">|</span>
                <button
                  type="button"
                  onClick={() => void handleBatchToggle(false)}
                  disabled={batchProcessing}
                  className="text-[12px] text-red hover:underline disabled:opacity-50"
                >
                  批量暂停
                </button>
              </div>
            )}
          </div>
          <h1 className="mb-1.5 text-[26px] font-black text-gray-900">信源管理</h1>
          <p className="text-[13px] text-gray-400">
            共 <b className="font-mono text-gray-600">{total}</b> 个信源 ·
            活跃 <b className="font-mono text-teal">{activeCount}</b> 个
          </p>
        </div>
        <Toolbar>
          <Button
            type="button"
            variant="primary"
            onClick={() => {
              setForm(emptyForm);
              setShowAddModal(true);
            }}
            className="whitespace-nowrap"
          >
            <Plus size={15} strokeWidth={2.2} />
            添加信源
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => opmlInputRef.current?.click()}
            className="whitespace-nowrap"
          >
            <Upload size={15} strokeWidth={2} />
            导入 OPML
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => setShowBatchImport(true)}
            className="whitespace-nowrap"
          >
            <FileSearch size={15} strokeWidth={2} />
            批量导入
          </Button>
        </Toolbar>
        <input ref={opmlInputRef} type="file" accept=".opml,.xml" className="hidden" onChange={handleOPMLImport} />
        <input ref={batchImportInputRef} type="file" accept=".json,.md,.txt,.opml,.xml" className="hidden" onChange={handleBatchImportFile} />
      </div>

      {/* Search & Filter Bar */}
      <Toolbar className="mb-4">
        <input
          type="text"
          placeholder="搜索名称 / URL / 平台 / 分类..."
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          className="h-9 w-56 rounded-sm border border-gray-200 bg-white px-3.5 text-[13px] outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
        />
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="h-9 cursor-pointer rounded-sm border border-gray-200 bg-white px-3 text-[13px] outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
        >
          <option value="">全部类型</option>
          <option value="RSS">RSS</option>
          <option value="RSSHub">RSSHub</option>
          <option value="TwitterRSS">Twitter RSS</option>
          <option value="Reddit">Reddit</option>
          <option value="API">API</option>
          <option value="Zhihu">知乎</option>
          <option value="网站">网站</option>
        </select>
        <select
          value={filterEnabled === undefined ? '' : filterEnabled ? 'yes' : 'no'}
          onChange={(e) => setFilterEnabled(e.target.value === '' ? undefined : e.target.value === 'yes')}
          className="h-9 cursor-pointer rounded-sm border border-gray-200 bg-white px-3 text-[13px] outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
        >
          <option value="">全部状态</option>
          <option value="yes">已启用</option>
          <option value="no">已禁用</option>
        </select>
        {(searchKeyword || filterType || filterEnabled !== undefined) && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => { setSearchKeyword(''); setFilterType(''); setFilterEnabled(undefined); }}
          >
            清除筛选
          </Button>
        )}
      </Toolbar>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-2.5">
        <div className="inline-flex rounded-sm border border-gray-200 bg-gray-100 p-0.5">
          {[
            { key: 'map' as const, label: '信源地图', icon: Network },
            { key: 'sync' as const, label: '同步看板', icon: Activity },
            { key: 'list' as const, label: '列表管理', icon: List },
          ].map((item) => {
            const Icon = item.icon;
            const active = viewMode === item.key;
            return (
              <button
                type="button"
                key={item.key}
                onClick={() => setViewMode(item.key)}
                className={cx(
                  'inline-flex items-center gap-1.5 rounded-xs border border-transparent px-3 py-1.5 text-[13px] transition',
                  active ? 'bg-white font-black text-primary shadow-sm' : 'font-semibold text-gray-500 hover:text-gray-800',
                )}
              >
                <Icon size={15} strokeWidth={2} />
                {item.label}
              </button>
            );
          })}
        </div>
        <span className="text-xs text-gray-400">
          当前统计全部 {mapSources.length} 个匹配信源
        </span>
      </div>

      {/* Error Banner */}
      {rsshubError && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-sm border border-red-light bg-red-light px-4 py-2.5 text-[13px] text-red">
          <span>{rsshubError}</span>
          <button type="button" onClick={() => setRsshubError(null)} className="px-1 text-base font-black leading-none text-red">×</button>
        </div>
      )}

      {error && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-sm border border-red-light bg-red-light px-4 py-2.5 text-[13px] text-red">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} className="px-1 text-base font-black leading-none text-red">×</button>
        </div>
      )}

      {/* Status filter tabs — applies to all source list views */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-gray-500">状态筛选：</span>
        {([
          { value: 'all', label: '全部', count: sourceMap.tiers ? Object.values(sourceMap.tiers).reduce((s, arr) => s + arr.length, 0) : 0 },
          { value: 'active', label: '正常', count: sourceMap.tiers ? Object.values(sourceMap.tiers).reduce((s, arr) => s + arr.filter((x) => x.status === 'active' && x.enabled).length, 0) : 0 },
          { value: 'syncing', label: '同步中', count: sourceMap.tiers ? Object.values(sourceMap.tiers).reduce((s, arr) => s + arr.filter((x) => x.status === 'syncing').length, 0) : 0 },
          { value: 'error', label: '错误', count: sourceMap.tiers ? Object.values(sourceMap.tiers).reduce((s, arr) => s + arr.filter((x) => x.status === 'error' || (x.enabled && x.sync_error)).length, 0) : 0 },
          { value: 'disabled', label: '已暂停', count: sourceMap.tiers ? Object.values(sourceMap.tiers).reduce((s, arr) => s + arr.filter((x) => !x.enabled || x.status === 'disabled').length, 0) : 0 },
        ] as const).map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setStatusFilter(tab.value as typeof statusFilter)}
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

      {viewMode === 'map' && (
        <SourceMapView
          sourceMap={filteredSourceMap}
          syncingIds={syncingIds}
          favoriteTargets={new Set([...favoriteTargets, ...sourceFavoriteKeys])}
          favoriteTargetPendingKeys={favoriteTargetPendingKeys}
          onEdit={openEditModal}
          onSync={handleSync}
          onToggleEnabled={handleToggleEnabled}
          onFavorite={handleToggleSourceFavorite}
          onMove={handleMoveSourceTier}
        />
      )}

      {viewMode === 'sync' && (
        <SourceSyncBoard
          syncBoard={syncBoard}
          syncingIds={syncingIds}
          syncResults={syncResults}
          now={new Date()}
          onEdit={openEditModal}
          onSync={handleSync}
        />
      )}

      {viewMode === 'list' && (
        <>
          {/* RSSHub Instances Manager */}
          <Panel className="mb-5 p-5">
            <div className="mb-3.5 flex items-center justify-between gap-3">
              <div>
                <h2 className="mb-0.5 text-[15px] font-black text-gray-800">RSSHub 实例</h2>
                <p className="text-xs text-gray-400">按优先级顺序尝试，禁用则跳过。添加小红书/微博/B站等路由时使用。</p>
              </div>
              {rsshubSaving && <span className="text-xs text-gray-400">保存中…</span>}
            </div>

            <div className="mb-3 flex flex-col gap-2">
              {rsshubLoading ? (
                <div className="py-2 text-[13px] text-gray-400">加载中…</div>
              ) : rsshubInstances.length === 0 ? (
                <div className="py-2 text-[13px] text-gray-400">暂无实例</div>
              ) : (
                rsshubInstances.map((inst, idx) => (
                  <div key={inst.url} className="flex items-center gap-2.5 rounded-sm border border-gray-100 bg-gray-50 px-3 py-2">
                    <span className="min-w-4 font-mono text-[11px] text-gray-300">#{idx + 1}</span>
                    <span className={cx('flex-1 break-all font-mono text-[13px]', inst.enabled ? 'text-gray-800' : 'text-gray-400')}>{inst.url}</span>
                    {inst.note && <span className="text-[11px] text-gray-400">{inst.note}</span>}
                    <button
                      type="button"
                      onClick={() => toggleInstance(inst.url)}
                      disabled={rsshubSaving}
                      className={cx(
                        'rounded-full px-2.5 py-1 text-[11px] font-black transition disabled:cursor-wait disabled:opacity-60',
                        inst.enabled ? 'bg-teal-light text-teal' : 'bg-gray-200 text-gray-400',
                      )}
                    >
                      {inst.enabled ? '启用' : '禁用'}
                    </button>
                    <Button
                      type="button"
                      variant="danger"
                      onClick={() => deleteInstance(inst.url)}
                      disabled={rsshubSaving}
                      className="min-h-7 px-2 py-1 text-[11px]"
                    >
                      删除
                    </Button>
                  </div>
                ))
              )}
            </div>

            <div className="flex gap-2">
              <input
                type="text"
                value={newInstanceUrl}
                onChange={(e) => setNewInstanceUrl(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addInstance()}
                placeholder="https://rsshub.example.com"
                className="h-9 flex-1 rounded-sm border border-gray-200 px-3 font-mono text-[13px] outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
              />
              <Button type="button" variant="primary" onClick={addInstance} disabled={rsshubSaving || !newInstanceUrl.trim()}>
                + 添加实例
              </Button>
            </div>
          </Panel>

          {/* Loading State */}
          {loading && sources.length === 0 && (
            <div className="flex h-52 items-center justify-center gap-2.5 text-sm text-gray-400">
              <Spinner />
              <span>加载中…</span>
            </div>
          )}

          {/* Table */}
          {!loading && (
            <Panel className="overflow-hidden">
              <div className="grid grid-cols-[2fr_1fr_1fr_1.2fr_1fr_1fr_0.8fr_1.5fr] border-b border-gray-200 bg-gray-50 px-6 py-3 text-xs font-black uppercase tracking-[0.05em] text-gray-500">
                {['名称', '类型', '分类', '最后同步', '采集频率', '权重', '状态', '操作'].map((h) => (
                  <div key={h}>{h}</div>
                ))}
              </div>
              {sources.length === 0 && (
                <div className="px-6 py-12 text-center text-sm text-gray-400">暂无信源，点击「添加信源」开始</div>
              )}
              {sources.map((src) => (
                <SourceRowComponent key={src.id} source={src} syncing={syncingIds.has(src.id)} syncResult={syncResults[src.id] || null}
                  deleting={deletingIds.has(src.id)} onSync={() => handleSync(src.id)} onEdit={() => openEditModal(src)}
                  onDelete={() => handleDelete(src.id)} onWeightChange={(w) => handleWeightChange(src.id, w)}
                  onIntervalChange={(mins) => handleIntervalChange(src.id, mins)}
                  favorite={favoriteTargets.has(getFavoriteTargetKey({ target_type: 'source', target_id: src.id })) || sourceFavoriteKeys.has(getFavoriteTargetKey({ target_type: 'source', target_id: src.id }))}
                  favoritePending={favoriteTargetPendingKeys.has(getFavoriteTargetKey({ target_type: 'source', target_id: src.id }))}
                  onFavorite={() => handleToggleSourceFavorite(src)}
                  selected={selectedIds.has(src.id)}
                  onSelect={handleSelectSource}
                />
              ))}
            </Panel>
          )}

          {/* Pagination */}
          {total > pageSize && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 py-3 text-[13px] text-gray-500">
              <span>
                第 {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} 条，共 {total} 条
              </span>
              <div className="flex flex-wrap gap-1.5">
                <Button type="button" variant="secondary" disabled={page <= 1} onClick={() => fetchSources(page - 1)} className="min-h-8 px-3.5 py-1.5 text-[13px] disabled:cursor-not-allowed">
                  上一页
                </Button>
                {Array.from({ length: Math.ceil(total / pageSize) }, (_, i) => i + 1)
                  .filter((p) => {
                    // Show first, last, and ±2 around current
                    if (p === 1 || p === Math.ceil(total / pageSize)) return true;
                    return Math.abs(p - page) <= 2;
                  })
                  .map((p, idx, arr) => {
                    const pages = arr;
                    const showEllipsis = idx > 0 && p - pages[idx - 1] > 1;
                    return (
                      <React.Fragment key={p}>
                        {showEllipsis && <span className="px-1 py-1.5 text-gray-400">…</span>}
                        <Button
                          type="button"
                          variant={p === page ? 'primary' : 'secondary'}
                          onClick={() => fetchSources(p)}
                          disabled={p === page}
                          className="min-h-8 px-3 py-1.5 text-[13px]"
                        >
                          {p}
                        </Button>
                      </React.Fragment>
                    );
                  })}
                <Button
                  type="button"
                  variant="secondary"
                  disabled={page >= Math.ceil(total / pageSize)}
                  onClick={() => fetchSources(page + 1)}
                  className="min-h-8 px-3.5 py-1.5 text-[13px] disabled:cursor-not-allowed"
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Add Source Modal */}
      {showAddModal && (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 px-4"
          onClick={() => setShowAddModal(false)}>
          <Panel onClick={(e) => e.stopPropagation()} className="w-full max-w-[480px] p-8 shadow-2xl">
            <h2 className="mb-6 text-xl font-black text-gray-900">添加信源</h2>
            <SourceForm form={form} setForm={setForm} />
            <div className="mt-7 flex justify-end gap-3">
              <Button type="button" variant="secondary" onClick={() => setShowAddModal(false)} disabled={submitting} className="px-5">
                取消
              </Button>
              <Button type="button" variant="primary" onClick={handleCreate} disabled={submitting || !form.name.trim()} className="px-5">
                {submitting ? '提交中…' : '添加'}
              </Button>
            </div>
          </Panel>
        </div>
      )}

      {/* Batch Import Modal */}
      {showBatchImport && (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 px-4"
          onClick={() => setShowBatchImport(false)}
        >
          <Panel onClick={(event) => event.stopPropagation()} className="flex max-h-[86vh] w-full max-w-[860px] flex-col overflow-hidden p-0 shadow-2xl">
            <div className="border-b border-gray-100 px-6 py-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="mb-1 text-xl font-black text-gray-900">批量导入信源</h2>
                  <p className="text-xs leading-5 text-gray-500">
                    支持粘贴信源配置、JSON 数组、Markdown 链接清单或 OPML 内容；先预览重复项，再确认写入。
                  </p>
                </div>
                <Button type="button" variant="ghost" onClick={() => setShowBatchImport(false)} className="min-h-8 px-2">
                  ×
                </Button>
              </div>
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="border-r border-gray-100 p-5">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <input
                    value={batchImportCategory}
                    onChange={(event) => setBatchImportCategory(event.target.value)}
                    placeholder="导入分类"
                    className="h-9 w-44 rounded-sm border border-gray-200 px-3 text-[13px] outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
                  />
                  <Button type="button" variant="secondary" onClick={() => batchImportInputRef.current?.click()}>
                    <Upload size={15} />
                    选择文件
                  </Button>
                  <Button type="button" variant="primary" onClick={handleBatchImportPreview} disabled={batchImportPreviewing || !batchImportContent.trim()}>
                    {batchImportPreviewing ? '预览中…' : '解析预览'}
                  </Button>
                </div>
                <textarea
                  value={batchImportContent}
                  onChange={(event) => {
                    setBatchImportContent(event.target.value);
                    setBatchImportPreview([]);
                  }}
                  placeholder={'粘贴 JSON / Markdown / OPML 信源配置，或类似：\n- [OpenAI Blog](https://openai.com/blog/rss.xml)\n- https://example.com/feed.xml'}
                  className="h-[420px] w-full resize-none rounded-sm border border-gray-200 bg-gray-50 p-3 font-mono text-xs leading-6 text-gray-700 outline-none transition focus:border-primary-border focus:bg-white focus:ring-2 focus:ring-primary-light"
                />
              </div>

              <div className="flex min-h-0 flex-col p-5">
                <div className="mb-3 grid grid-cols-3 gap-2">
                  <div className="rounded-sm border border-gray-100 bg-gray-50 p-2.5">
                    <div className="text-[10px] text-gray-400">识别</div>
                    <div className="font-mono text-xl font-black text-gray-900">{batchImportPreview.length}</div>
                  </div>
                  <div className="rounded-sm border border-gray-100 bg-gray-50 p-2.5">
                    <div className="text-[10px] text-gray-400">可导入</div>
                    <div className="font-mono text-xl font-black text-teal">{batchImportPreview.filter((item) => !item.duplicate).length}</div>
                  </div>
                  <div className="rounded-sm border border-gray-100 bg-gray-50 p-2.5">
                    <div className="text-[10px] text-gray-400">重复</div>
                    <div className="font-mono text-xl font-black text-amber">{batchImportPreview.filter((item) => item.duplicate).length}</div>
                  </div>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto rounded-sm border border-gray-100">
                  {batchImportPreview.length === 0 ? (
                    <div className="p-6 text-center text-xs leading-6 text-gray-400">
                      解析后会在这里显示信源名称、类型和重复状态。
                    </div>
                  ) : batchImportPreview.map((item) => (
                    <div key={item.url} className="border-b border-gray-100 p-3 last:border-b-0">
                      <div className="mb-1 flex items-start justify-between gap-2">
                        <div className="min-w-0 truncate text-[13px] font-black text-gray-800">{item.name}</div>
                        <Badge tone={item.duplicate ? 'amber' : 'teal'} className="shrink-0 py-0.5">
                          {item.duplicate ? '重复' : '新增'}
                        </Badge>
                      </div>
                      <div className="break-all font-mono text-[11px] leading-5 text-gray-400">{item.url}</div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">{sourceTypeLabel(item.source_type)}</span>
                        <span className="rounded bg-primary-light px-1.5 py-0.5 text-[10px] text-primary">{item.category}</span>
                        {item.platform && <span className="rounded bg-teal-light px-1.5 py-0.5 text-[10px] text-teal">{item.platform}</span>}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-4 flex justify-end gap-2">
                  <Button type="button" variant="secondary" onClick={() => setShowBatchImport(false)} disabled={batchImporting}>
                    取消
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    onClick={handleBatchImport}
                    disabled={batchImporting || batchImportPreview.filter((item) => !item.duplicate).length === 0}
                  >
                    {batchImporting ? '导入中…' : '确认导入'}
                  </Button>
                </div>
              </div>
            </div>
          </Panel>
        </div>
      )}

      {/* Edit Source Modal */}
      {editingSource && (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30 px-4"
          onClick={() => { setEditingSource(null); setForm(emptyForm); }}>
          <Panel onClick={(e) => e.stopPropagation()} className="w-full max-w-[480px] p-8 shadow-2xl">
            <h2 className="mb-6 text-xl font-black text-gray-900">编辑信源</h2>
            <SourceForm form={form} setForm={setForm} />
            <div className="mt-7 flex justify-end gap-3">
              <Button type="button" variant="secondary" onClick={() => { setEditingSource(null); setForm(emptyForm); }} disabled={submitting} className="px-5">
                取消
              </Button>
              <Button type="button" variant="primary" onClick={handleUpdate} disabled={submitting || !form.name.trim()} className="px-5">
                {submitting ? '保存中…' : '保存'}
              </Button>
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}
