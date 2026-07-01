'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Archive,
  CheckSquare,
  Filter,
  Inbox,
  RefreshCw,
  Search,
  Star,
  Trash2,
  Video,
  X,
} from 'lucide-react';
import { creationApi, favoritesApi } from '@/lib/api';
import { useAppContext } from '@/components/ClientLayout';
import CreationPlanDisplay, { type CreationPlan } from '@/components/CreationPlanDisplay';
import { Badge, Button, Panel, cx } from '@/components/ui';
import type { FavoriteItem, FavoriteStatus, FavoriteTargetType } from '@/types';
import {
  BatchActionBar,
  BoardGrid,
  CreationDraftPanel,
  DirtyStatusBar,
  ErrorBanner,
  FiltersBar,
  HeaderStats,
} from './_components';
import {
  STATUS_FLOW,
  TYPE_OPTIONS,
  STATUS_OPTIONS,
  CREATION_PLATFORMS,
  FAVORITES_PAGE_SIZE,
  TYPE_LABEL,
  TYPE_TONE,
  STATUS_LABEL,
  getFavoriteTags,
  getSavedCreationPlans,
  parseTagInput,
  withSavedCreationPlan,
  getInitialFavoriteFilters,
} from './_favorites-utils';

export default function FavoritesPage() {
  const { refreshCounts } = useAppContext();
  const initialFilters = useMemo(() => getInitialFavoriteFilters(), []);
  const [items, setItems] = useState<FavoriteItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [targetType, setTargetType] = useState<FavoriteTargetType | ''>(initialFilters.targetType);
  const [status, setStatus] = useState<FavoriteStatus | ''>(initialFilters.status);
  const [keyword, setKeyword] = useState(initialFilters.keyword);
  const [draftKeyword, setDraftKeyword] = useState(initialFilters.keyword);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkPending, setBulkPending] = useState(false);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<{ status: FavoriteStatus; beforeId: number | null } | null>(null);
  const [dirtyStatuses, setDirtyStatuses] = useState<Set<FavoriteStatus>>(new Set());
  const [savingOrder, setSavingOrder] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);
  const [creationDraft, setCreationDraft] = useState<{
    item: FavoriteItem;
    platform: string;
    plan: CreationPlan;
  } | null>(null);
  const [creatingKey, setCreatingKey] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editNote, setEditNote] = useState('');
  const [editTags, setEditTags] = useState('');
  const [editPending, setEditPending] = useState(false);

  const fetchFavorites = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setDraggingId(null);
      setDropTarget(null);
      const firstPage = await favoritesApi.list({
        page: 1,
        page_size: FAVORITES_PAGE_SIZE,
        target_type: targetType,
        status,
        keyword: keyword.trim() || undefined,
      });
      const totalItems = firstPage.total || 0;
      const totalPages = Math.ceil(totalItems / FAVORITES_PAGE_SIZE);
      const allItems = [...(firstPage.items || [])];
      if (totalPages > 1) {
        const rest = await Promise.all(
          Array.from({ length: totalPages - 1 }, (_, index) => favoritesApi.list({
            page: index + 2,
            page_size: FAVORITES_PAGE_SIZE,
            target_type: targetType,
            status,
            keyword: keyword.trim() || undefined,
          }))
        );
        rest.forEach((page) => allItems.push(...(page.items || [])));
      }
      setItems(allItems);
      setTotal(totalItems);
      setSelectedIds(new Set());
      setDirtyStatuses(new Set());
      setSavedNotice(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '收藏夹加载失败');
    } finally {
      setLoading(false);
    }
  }, [targetType, status, keyword]);

  useEffect(() => {
    void fetchFavorites();
  }, [fetchFavorites]);

  const counts = useMemo(() => {
    const byStatus = STATUS_FLOW.reduce((acc, column) => {
      acc[column.value] = items.filter((item) => item.status === column.value).length;
      return acc;
    }, {} as Record<FavoriteStatus, number>);
    const byType = TYPE_OPTIONS.filter((option) => option.value).map((option) => ({
      type: option.value as FavoriteTargetType,
      label: option.label,
      count: items.filter((item) => item.target_type === option.value).length,
    })).filter((item) => item.count > 0);
    const active = items.filter((item) => item.status !== 'archived').length;
    return { byStatus, byType, active };
  }, [items]);

  const boardColumns = useMemo(() => {
    const columns = status ? STATUS_FLOW.filter((column) => column.value === status) : STATUS_FLOW;
    return columns.map((column) => ({
      ...column,
      items: items
        .filter((item) => item.status === column.value)
        .sort((a, b) => a.position - b.position || b.updated_at.localeCompare(a.updated_at) || b.id - a.id),
    }));
  }, [items, status]);

  const selectedItems = useMemo(
    () => items.filter((item) => selectedIds.has(item.id)),
    [items, selectedIds],
  );
  const dragEnabled = !targetType && !keyword.trim() && total === items.length;

  useEffect(() => {
    if (!dragEnabled && draggingId !== null) {
      setDraggingId(null);
      setDropTarget(null);
    }
  }, [dragEnabled, draggingId]);

  const favoriteMatchesFilters = useCallback((item: FavoriteItem) => {
    if (targetType && item.target_type !== targetType) return false;
    if (status && item.status !== status) return false;
    const query = keyword.trim().toLowerCase();
    if (!query) return true;
    return [item.title, item.note, item.source_name, item.target_key]
      .some((value) => String(value || '').toLowerCase().includes(query));
  }, [keyword, status, targetType]);

  const applyFavoriteUpdates = useCallback((updatedItems: FavoriteItem[]) => {
    if (updatedItems.length === 0) return;
    const byId = new Map(updatedItems.map((item) => [item.id, item]));
    const removedIds = new Set<number>();
    const nextItems = items.flatMap((item) => {
      const updated = byId.get(item.id);
      if (!updated) return [item];
      if (favoriteMatchesFilters(updated)) return [updated];
      removedIds.add(item.id);
      return [];
    });

    setItems(nextItems);
    if (removedIds.size > 0) {
      setTotal((prev) => Math.max(0, prev - removedIds.size));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const id of removedIds) next.delete(id);
        return next;
      });
    }
  }, [favoriteMatchesFilters, items]);

  const handleSearch = () => setKeyword(draftKeyword);

  const startEdit = (item: FavoriteItem) => {
    setEditingId(item.id);
    setEditNote(item.note || '');
    setEditTags(getFavoriteTags(item).join(', '));
    setError(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditNote('');
    setEditTags('');
  };

  const saveFavoriteMeta = async (item: FavoriteItem) => {
    setEditPending(true);
    setError(null);
    try {
      const updated = await favoritesApi.update(item.id, {
        note: editNote.trim() || null,
        tags: parseTagInput(editTags),
      });
      applyFavoriteUpdates([updated]);
      cancelEdit();
    } catch (err) {
      setError(err instanceof Error ? err.message : '收藏备注保存失败');
    } finally {
      setEditPending(false);
    }
  };

  const toggleSelected = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectColumn = (columnItems: FavoriteItem[]) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const allSelected = columnItems.every((item) => next.has(item.id));
      for (const item of columnItems) {
        if (allSelected) next.delete(item.id);
        else next.add(item.id);
      }
      return next;
    });
  };

  const updateStatus = async (item: FavoriteItem, nextStatus: FavoriteStatus) => {
    setPendingId(item.id);
    setError(null);
    try {
      const updated = await favoritesApi.update(item.id, { status: nextStatus });
      applyFavoriteUpdates([updated]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '状态更新失败');
    } finally {
      setPendingId(null);
    }
  };

  const moveFavorite = useCallback((itemId: number, targetStatus: FavoriteStatus, beforeId: number | null) => {
    const movingItem = items.find((item) => item.id === itemId);
    if (!movingItem) return;
    if (itemId === beforeId) {
      setDraggingId(null);
      setDropTarget(null);
      return;
    }

    const previousItems = items;
    const sourceStatus = movingItem.status;
    const sourceColumnItems = previousItems
      .filter((item) => item.status === sourceStatus && item.id !== itemId)
      .sort((a, b) => a.position - b.position || b.updated_at.localeCompare(a.updated_at) || b.id - a.id);
    const targetColumnItems = previousItems
      .filter((item) => item.status === targetStatus && item.id !== itemId)
      .sort((a, b) => a.position - b.position || b.updated_at.localeCompare(a.updated_at) || b.id - a.id);
    const targetIndex = beforeId ? targetColumnItems.findIndex((item) => item.id === beforeId) : -1;
    const insertIndex = targetIndex >= 0 ? targetIndex : targetColumnItems.length;
    const nextColumnItems = [
      ...targetColumnItems.slice(0, insertIndex),
      { ...movingItem, status: targetStatus },
      ...targetColumnItems.slice(insertIndex),
    ];
    const nextPositions = new Map<number, number>();
    for (const [index, item] of nextColumnItems.entries()) {
      nextPositions.set(item.id, (index + 1) * 1000);
    }
    if (sourceStatus !== targetStatus) {
      for (const [index, item] of sourceColumnItems.entries()) {
        nextPositions.set(item.id, (index + 1) * 1000);
      }
    }

    setItems((prev) => prev.map((item) => {
      const nextPosition = nextPositions.get(item.id);
      if (item.id === itemId) return { ...item, status: targetStatus, position: nextPosition || item.position };
      if (nextPosition !== undefined) return { ...item, position: nextPosition };
      return item;
    }));
    setDirtyStatuses((prev) => {
      const next = new Set(prev);
      next.add(targetStatus);
      if (sourceStatus !== targetStatus && sourceColumnItems.length > 0) next.add(sourceStatus);
      return next;
    });
    setDraggingId(null);
    setDropTarget(null);
    setError(null);
    setSavedNotice(null);
  }, [items]);

  const saveOrder = useCallback(async () => {
    if (dirtyStatuses.size === 0) return;
    setSavingOrder(true);
    setError(null);
    try {
      const reorderTargets = Array.from(dirtyStatuses).map((dirtyStatus) => {
        const orderedIds = items
          .filter((item) => item.status === dirtyStatus)
          .sort((a, b) => a.position - b.position || b.updated_at.localeCompare(a.updated_at) || b.id - a.id)
          .map((item) => item.id);
        return { status: dirtyStatus, orderedIds };
      });
      const updatedItems = reorderTargets.length > 0
        ? await favoritesApi.reorderBoard(reorderTargets)
        : [];
      const byId = new Map(updatedItems.map((item) => [item.id, item]));
      setItems((prev) => prev.map((item) => byId.get(item.id) || item));
      setDirtyStatuses(new Set());
      setSavedNotice('排序已保存');
    } catch (err) {
      const message = err instanceof Error ? err.message : '排序保存失败';
      await fetchFavorites();
      setError(`${message}，已恢复服务器排序`);
    } finally {
      setSavingOrder(false);
    }
  }, [dirtyStatuses, fetchFavorites, items]);

  const updateSelectedStatus = async (nextStatus: FavoriteStatus) => {
    if (selectedItems.length === 0) return;
    setBulkPending(true);
    setError(null);
    try {
      const updated = await favoritesApi.bulkStatus(nextStatus, selectedItems.map((item) => item.id));
      applyFavoriteUpdates(updated);
      setSelectedIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : '批量更新失败');
    } finally {
      setBulkPending(false);
    }
  };

  const removeFavorite = async (item: FavoriteItem) => {
    setPendingId(item.id);
    setError(null);
    try {
      await favoritesApi.delete(item.id);
      setItems((prev) => prev.filter((row) => row.id !== item.id));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(item.id);
        return next;
      });
      setTotal((prev) => Math.max(0, prev - 1));
      refreshCounts();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除收藏失败');
    } finally {
      setPendingId(null);
    }
  };

  const removeSelected = async () => {
    if (selectedItems.length === 0) return;
    setBulkPending(true);
    setError(null);
    try {
      await favoritesApi.bulkDelete(selectedItems.map((item) => item.id));
      setItems((prev) => prev.filter((item) => !selectedIds.has(item.id)));
      setTotal((prev) => Math.max(0, prev - selectedItems.length));
      setSelectedIds(new Set());
      refreshCounts();
    } catch (err) {
      setError(err instanceof Error ? err.message : '批量删除失败');
    } finally {
      setBulkPending(false);
    }
  };

  const generateCreationPlan = async (item: FavoriteItem, platform: string) => {
    if (item.target_type !== 'content' || !item.target_id) return;
    const creatingId = `${item.id}:${platform}`;
    setCreatingKey(creatingId);
    setError(null);
    try {
      const plan = await creationApi.generatePlan(item.target_id, platform) as CreationPlan;
      const planPlatform = plan._meta?.platform || platform;
      const updated = await favoritesApi.update(item.id, {
        status: 'drafting',
        snapshot: withSavedCreationPlan(item, planPlatform, plan),
      });
      setCreationDraft({ item: updated, platform: planPlatform, plan });
      applyFavoriteUpdates([updated]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '创作方案生成失败');
    } finally {
      setCreatingKey(null);
    }
  };

  const openSavedCreationPlan = (item: FavoriteItem, platform: string) => {
    const plan = getSavedCreationPlans(item)[platform];
    if (!plan) return;
    setCreationDraft({ item, platform: plan._meta?.platform || platform, plan });
  };

  return (
    <div className="fade-in h-full overflow-y-auto bg-[#F8FAFC] px-6 py-6 lg:px-10 lg:py-8">
      <HeaderStats total={total} activeCount={counts.active} counts={counts} />

      <FiltersBar
        targetType={targetType}
        setTargetType={setTargetType}
        status={status}
        setStatus={setStatus}
        draftKeyword={draftKeyword}
        setDraftKeyword={setDraftKeyword}
        handleSearch={handleSearch}
        countsByType={counts.byType}
      />

      <BatchActionBar
        selectedCount={selectedIds.size}
        bulkPending={bulkPending}
        onMoveToStatus={(v) => void updateSelectedStatus(v)}
        onArchive={() => void updateSelectedStatus('archived')}
        onRemove={() => void removeSelected()}
      />

      <ErrorBanner error={error} onRetry={() => void fetchFavorites()} />

      {creationDraft && (
        <CreationDraftPanel
          draft={creationDraft}
          platformLabel={CREATION_PLATFORMS.find((p) => p.id === creationDraft.platform)?.label || creationDraft.platform}
          onClose={() => setCreationDraft(null)}
        />
      )}

      <DirtyStatusBar
        dirtyCount={dirtyStatuses.size}
        savedNotice={savedNotice}
        saving={savingOrder}
        onDiscard={() => void fetchFavorites()}
        onSave={() => void saveOrder()}
      />

      <BoardGrid
        loading={loading}
        items={items}
        boardColumns={boardColumns}
        selectedIds={selectedIds}
        pendingId={pendingId}
        editingId={editingId}
        editNote={editNote}
        editTags={editTags}
        editPending={editPending}
        creatingKey={creatingKey}
        draggingId={draggingId}
        dropTarget={dropTarget}
        dragEnabled={dragEnabled}
        onSelectColumn={selectColumn}
        onSelect={toggleSelected}
        onStatus={updateStatus}
        onRemove={removeFavorite}
        onGeneratePlan={generateCreationPlan}
        onOpenSavedPlan={openSavedCreationPlan}
        onStartEdit={startEdit}
        onCancelEdit={cancelEdit}
        onEditNote={setEditNote}
        onEditTags={setEditTags}
        onSaveMeta={saveFavoriteMeta}
        onDragStart={setDraggingId}
        onDragHover={setDropTarget}
        onDragEnd={() => {
          setDraggingId(null);
          setDropTarget(null);
        }}
        onMove={moveFavorite}
      />
    </div>
  );
}

