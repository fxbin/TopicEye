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
import {
  type SourceTierKey,
  type DropTarget,
  sourceTierMeta,
  getSourceTier,
  normalizeRsshubInstanceUrl,
  isPlainObject,
  validateApiSourceConfig,
} from './_sources-utils';

import { SourceMapCard, SourceMapView } from './_components';
import { AddSourceModal, BatchImportModal, EditSourceModal } from './_modals';
import { RSSHubManager, SourceListPanel } from './_panels';

// ─── Page Component ───

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
          <RSSHubManager
            instances={rsshubInstances}
            loading={rsshubLoading}
            saving={rsshubSaving}
            newInstanceUrl={newInstanceUrl}
            setNewInstanceUrl={setNewInstanceUrl}
            onToggle={toggleInstance}
            onDelete={deleteInstance}
            onAdd={addInstance}
          />
          <SourceListPanel
            loading={loading}
            sources={sources}
            syncingIds={syncingIds}
            syncResults={syncResults}
            deletingIds={deletingIds}
            total={total}
            page={page}
            pageSize={pageSize}
            favoriteTargets={favoriteTargets}
            favoriteTargetPendingKeys={favoriteTargetPendingKeys}
            sourceFavoriteKeys={sourceFavoriteKeys}
            selectedIds={selectedIds}
            onSync={handleSync}
            onEdit={openEditModal}
            onDelete={handleDelete}
            onWeightChange={handleWeightChange}
            onIntervalChange={handleIntervalChange}
            onFavorite={handleToggleSourceFavorite}
            onSelect={handleSelectSource}
            onPageChange={(p) => void fetchSources(p)}
          />
        </>
      )}

      {showAddModal && (
        <AddSourceModal form={form} setForm={setForm} submitting={submitting} onCreate={handleCreate} onClose={() => setShowAddModal(false)} />
      )}
      {showBatchImport && (
        <BatchImportModal
          batchImportContent={batchImportContent}
          setBatchImportContent={(v) => { setBatchImportContent(v); setBatchImportPreview([]); }}
          batchImportCategory={batchImportCategory}
          setBatchImportCategory={setBatchImportCategory}
          batchImportPreview={batchImportPreview}
          batchImportPreviewing={batchImportPreviewing}
          batchImporting={batchImporting}
          fileInputRef={batchImportInputRef}
          onPreview={handleBatchImportPreview}
          onImport={handleBatchImport}
          onClose={() => setShowBatchImport(false)}
        />
      )}
      {editingSource && (
        <EditSourceModal form={form} setForm={setForm} submitting={submitting} onUpdate={handleUpdate} onClose={() => { setEditingSource(null); setForm(emptyForm); }} />
      )}
    </div>
  );
}
