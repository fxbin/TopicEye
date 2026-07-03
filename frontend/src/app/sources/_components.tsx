'use client';

/**
 * Sources page 子组件（从 page.tsx 抽出的 2 个展示组件）。
 *
 * - SourceMapView   信源 4 层看板（core / stable / watch / attention）
 * - SourceMapCard   看板中单张信源卡片（含拖拽、收藏、同步状态）
 *
 * 配置 + 工具函数来自 _sources-utils.ts。
 */

import React, { useState } from 'react';
import { Activity, GripVertical, Network, Star } from 'lucide-react';
import { Badge, Button, Panel, cx } from '@/components/ui';
import type { BackendSource } from '@/components/SourceRow';
import { getFavoriteTargetKey } from '@/lib/favorites';
import { sourceTypeLabel } from '@/lib/source-sync-board';
import { timeAgo } from '@/lib/utils';
import type { SourceTierKey, DropTarget } from './_sources-utils';
import { sourceTierMeta, getSourceTier } from './_sources-utils';

export function SourceMapView({
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

export function SourceMapCard({
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
