'use client';

/**
 * Favorites page 子组件。
 *
 * 从 app/favorites/page.tsx 抽出的 3 个组件：
 * - StatPill          — 顶部统计徽章
 * - FavoriteColumn    — 单列看板（拖拽 / 全选 / 卡片列表）
 * - FavoriteCard      — 单卡片（标签、备注、状态切换、生成方案、操作按钮）
 *
 * 静态配置（STATUS_FLOW / TYPE_LABEL / TYPE_TONE / CREATION_PLATFORMS）和工具函数
 * 来自 _favorites-utils.ts，避免主页面重复 import。
 */

import React from 'react';
import {
  AlertCircle,
  Archive,
  BookOpen,
  CheckSquare,
  ExternalLink,
  FileText,
  Filter,
  GripVertical,
  Inbox,
  Layers3,
  PenLine,
  RefreshCw,
  Search,
  Square,
  Star,
  Trash2,
  X,
} from 'lucide-react';
import type { FavoriteItem, FavoriteStatus, FavoriteTargetType } from '@/types';
import { Badge, Button, Panel, cx } from '@/components/ui';
import CreationPlanDisplay from '@/components/CreationPlanDisplay';
import { timeAgo } from '@/lib/datetime';
import {
  CREATION_PLATFORMS,
  STATUS_FLOW,
  STATUS_LABEL,
  STATUS_OPTIONS,
  TYPE_LABEL,
  TYPE_OPTIONS,
  TYPE_TONE,
  getFavoriteTags,
  getSavedCreationPlans,
  getSnapshotMeta,
  getSnapshotText,
} from './_favorites-utils';

export function StatPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'primary' | 'teal' | 'amber' | 'neutral';
}) {
  const toneClass = {
    primary: 'text-primary bg-primary-light border-primary-border',
    teal: 'text-teal bg-teal-light border-teal-border',
    amber: 'text-amber bg-amber-light border-amber-border',
    neutral: 'text-gray-500 bg-gray-50 border-gray-200',
  }[tone];
  return (
    <div className={cx('rounded-sm border bg-white px-4 py-2', toneClass)}>
      <div className="text-[11px] font-black opacity-75">{label}</div>
      <div className="font-mono text-lg font-black">{value}</div>
    </div>
  );
}

type StatusFlowColumn = {
  value: FavoriteStatus;
  label: string;
  hint: string;
  tone: 'primary' | 'teal' | 'amber' | 'neutral';
  items: FavoriteItem[];
};

export function FavoriteColumn({
  column,
  selectedIds,
  pendingId,
  draggingId,
  dropTarget,
  dragEnabled,
  onSelectColumn,
  onSelect,
  onStatus,
  onRemove,
  onGeneratePlan,
  onOpenSavedPlan,
  creatingKey,
  editingId,
  editNote,
  editTags,
  editPending,
  onStartEdit,
  onCancelEdit,
  onEditNote,
  onEditTags,
  onSaveMeta,
  onDragStart,
  onDragHover,
  onDragEnd,
  onMove,
}: {
  column: StatusFlowColumn;
  selectedIds: Set<number>;
  pendingId: number | null;
  draggingId: number | null;
  dropTarget: { status: FavoriteStatus; beforeId: number | null } | null;
  dragEnabled: boolean;
  onSelectColumn: (items: FavoriteItem[]) => void;
  onSelect: (id: number) => void;
  onStatus: (item: FavoriteItem, status: FavoriteStatus) => void;
  onRemove: (item: FavoriteItem) => void;
  onGeneratePlan: (item: FavoriteItem, platform: string) => void;
  onOpenSavedPlan: (item: FavoriteItem, platform: string) => void;
  creatingKey: string | null;
  editingId: number | null;
  editNote: string;
  editTags: string;
  editPending: boolean;
  onStartEdit: (item: FavoriteItem) => void;
  onCancelEdit: () => void;
  onEditNote: (value: string) => void;
  onEditTags: (value: string) => void;
  onSaveMeta: (item: FavoriteItem) => void;
  onDragStart: (id: number) => void;
  onDragHover: (target: { status: FavoriteStatus; beforeId: number | null } | null) => void;
  onDragEnd: () => void;
  onMove: (itemId: number, status: FavoriteStatus, beforeId: number | null) => void;
}) {
  const allSelected = column.items.length > 0 && column.items.every((item) => selectedIds.has(item.id));
  const isColumnDropTarget = dropTarget?.status === column.value && dropTarget.beforeId === null;
  const draggedIdFrom = (event: React.DragEvent<HTMLElement>) => {
    const raw = event.dataTransfer.getData('text/plain');
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : draggingId;
  };
  return (
    <section
      data-favorite-column={column.value}
      onDragOver={(event) => {
        if (!draggingId) return;
        event.preventDefault();
        onDragHover({ status: column.value, beforeId: null });
      }}
      onDrop={(event) => {
        event.preventDefault();
        event.stopPropagation();
        const draggedId = draggedIdFrom(event);
        if (draggedId) onMove(draggedId, column.value, dropTarget?.beforeId ?? null);
      }}
      className={cx(
        'min-w-0 rounded-lg border bg-white transition',
        isColumnDropTarget ? 'border-primary-border shadow-[0_0_0_2px_rgba(255,107,53,0.10)]' : 'border-gray-200',
      )}
    >
      <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-3.5 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Badge tone={column.tone} className="rounded px-2 py-0.5">{column.label}</Badge>
            <span className="font-mono text-xs font-black text-gray-500">{column.items.length}</span>
          </div>
          <div className="mt-1 text-[11px] text-gray-400">{column.hint}</div>
        </div>
        <button
          type="button"
          disabled={column.items.length === 0}
          onClick={() => onSelectColumn(column.items)}
          aria-label={allSelected ? `取消选择${column.label}列` : `选择${column.label}列`}
          aria-pressed={allSelected}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-xs border border-gray-200 bg-white text-gray-400 transition hover:text-primary disabled:opacity-30"
          title={allSelected ? '取消选择本列' : '选择本列'}
        >
          {allSelected ? <CheckSquare size={15} /> : <Square size={15} />}
        </button>
      </div>
      <div className="flex min-h-[220px] flex-col gap-2 p-2.5">
        {column.items.length === 0 ? (
          <div className={cx(
            'grid min-h-[120px] place-items-center rounded-sm border border-dashed text-center text-xs transition',
            isColumnDropTarget ? 'border-primary-border bg-primary-light text-primary' : 'border-gray-200 bg-gray-50 text-gray-400',
          )}>
            {draggingId ? '拖到这里' : '暂无素材'}
          </div>
        ) : column.items.map((item) => (
          <FavoriteCard
            key={item.id}
            item={item}
            selected={selectedIds.has(item.id)}
            pending={pendingId === item.id}
            dragging={draggingId === item.id}
            dropBefore={dropTarget?.status === column.value && dropTarget.beforeId === item.id}
            dragEnabled={dragEnabled}
            onSelect={onSelect}
            onStatus={onStatus}
            onRemove={onRemove}
            onGeneratePlan={onGeneratePlan}
            onOpenSavedPlan={onOpenSavedPlan}
            creatingKey={creatingKey}
            editing={editingId === item.id}
            editNote={editNote}
            editTags={editTags}
            editPending={editPending}
            onStartEdit={onStartEdit}
            onCancelEdit={onCancelEdit}
            onEditNote={onEditNote}
            onEditTags={onEditTags}
            onSaveMeta={onSaveMeta}
            onDragStart={onDragStart}
            onDragHover={(beforeId) => onDragHover({ status: column.value, beforeId })}
            onDragEnd={onDragEnd}
            onDrop={(draggedId, beforeId) => onMove(draggedId, column.value, beforeId)}
          />
        ))}
      </div>
    </section>
  );
}

export function FavoriteCard({
  item,
  selected,
  pending,
  dragging,
  dropBefore,
  dragEnabled,
  onSelect,
  onStatus,
  onRemove,
  onGeneratePlan,
  onOpenSavedPlan,
  creatingKey,
  editing,
  editNote,
  editTags,
  editPending,
  onStartEdit,
  onCancelEdit,
  onEditNote,
  onEditTags,
  onSaveMeta,
  onDragStart,
  onDragHover,
  onDragEnd,
  onDrop,
}: {
  item: FavoriteItem;
  selected: boolean;
  pending: boolean;
  dragging: boolean;
  dropBefore: boolean;
  dragEnabled: boolean;
  onSelect: (id: number) => void;
  onStatus: (item: FavoriteItem, status: FavoriteStatus) => void;
  onRemove: (item: FavoriteItem) => void;
  onGeneratePlan: (item: FavoriteItem, platform: string) => void;
  onOpenSavedPlan: (item: FavoriteItem, platform: string) => void;
  creatingKey: string | null;
  editing: boolean;
  editNote: string;
  editTags: string;
  editPending: boolean;
  onStartEdit: (item: FavoriteItem) => void;
  onCancelEdit: () => void;
  onEditNote: (value: string) => void;
  onEditTags: (value: string) => void;
  onSaveMeta: (item: FavoriteItem) => void;
  onDragStart: (id: number) => void;
  onDragHover: (beforeId: number) => void;
  onDragEnd: () => void;
  onDrop: (draggedId: number, beforeId: number) => void;
}) {
  const snapshotText = getSnapshotText(item);
  const metaText = getSnapshotMeta(item);
  const tags = getFavoriteTags(item);
  const savedPlans = getSavedCreationPlans(item);
  const statusTone = item.status === 'inbox' ? 'amber' : item.status === 'researching' ? 'teal' : item.status === 'drafting' ? 'primary' : 'neutral';
  return (
    <article
      data-favorite-card-id={item.id}
      draggable={dragEnabled && !pending}
      onDragStart={(event) => {
        if (!dragEnabled) return;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(item.id));
        onDragStart(item.id);
      }}
      onDragOver={(event) => {
        if (!dragEnabled) return;
        event.preventDefault();
        event.stopPropagation();
        onDragHover(item.id);
      }}
      onDrop={(event) => {
        if (!dragEnabled) return;
        event.preventDefault();
        event.stopPropagation();
        const raw = event.dataTransfer.getData('text/plain');
        const draggedId = Number(raw);
        if (Number.isFinite(draggedId) && draggedId > 0) {
          onDrop(draggedId, item.id);
        }
      }}
      onDragEnd={onDragEnd}
      className={cx(
        'rounded-sm border bg-white p-3 transition hover:border-primary-border hover:shadow-sm',
        selected ? 'border-primary-border ring-1 ring-primary-border' : 'border-gray-200',
        dragging && 'opacity-45',
        dropBefore && 'border-primary-border shadow-[inset_0_3px_0_#FF6B35]',
      )}
    >
      <div className="mb-2 flex items-start gap-2">
        <div
          className="mt-0.5 grid h-5 w-5 shrink-0 cursor-grab place-items-center rounded-xs text-gray-300 transition hover:bg-gray-50 hover:text-primary active:cursor-grabbing"
          title={dragEnabled ? '拖拽排序' : '清除类型和关键词筛选后可拖拽排序'}
        >
          <GripVertical size={14} />
        </div>
        <button
          type="button"
          onClick={() => onSelect(item.id)}
          aria-label={selected ? '取消选择素材' : '选择素材'}
          aria-pressed={selected}
          className={cx('mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-xs border transition', selected ? 'border-primary bg-primary text-white' : 'border-gray-200 text-gray-300 hover:text-primary')}
          title={selected ? '取消选择' : '选择素材'}
        >
          {selected ? <CheckSquare size={13} /> : <Square size={13} />}
        </button>
        {item.cover_url && (
          // eslint-disable-next-line @next/next/no-img-element -- Favorite covers are arbitrary external URLs.
          <img
            src={item.cover_url}
            alt={item.title}
            className="h-14 w-10 shrink-0 rounded-xs border border-gray-100 bg-gray-100 object-cover"
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <Badge tone={TYPE_TONE[item.target_type]} className="rounded px-2 py-0.5">
              {TYPE_LABEL[item.target_type]}
            </Badge>
            <Badge tone={statusTone} className="rounded px-2 py-0.5">{STATUS_LABEL[item.status]}</Badge>
          </div>
          <h3 className="m-0 line-clamp-2 text-[13px] font-black leading-5 text-gray-900">{item.title}</h3>
        </div>
      </div>

      {metaText && <div className="mb-1.5 line-clamp-1 text-[11px] font-bold text-gray-400">{metaText}</div>}
      {snapshotText && <p className="mb-2.5 line-clamp-3 text-xs leading-5 text-gray-500">{snapshotText}</p>}
      {(item.note || tags.length > 0) && (
        <div className="mb-2.5 rounded-sm border border-gray-100 bg-gray-50 px-2.5 py-2">
          {item.note && <p className="mb-1.5 whitespace-pre-wrap text-xs leading-5 text-gray-600">{item.note}</p>}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {tags.map((tag) => (
                <span key={tag} className="rounded-full bg-white px-2 py-0.5 text-[10px] font-bold text-gray-500">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {editing && (
        <div className="mb-2.5 rounded-sm border border-primary-border bg-primary-light/35 p-2">
          <textarea
            value={editNote}
            onChange={(event) => onEditNote(event.target.value)}
            rows={3}
            className="mb-2 w-full resize-none rounded-xs border border-gray-200 bg-white px-2 py-1.5 text-xs leading-5 text-gray-700 outline-none focus:border-primary-border"
            placeholder="写下选题判断、创作角度或待验证问题"
          />
          <input
            value={editTags}
            onChange={(event) => onEditTags(event.target.value)}
            className="mb-2 h-8 w-full rounded-xs border border-gray-200 bg-white px-2 text-xs text-gray-700 outline-none focus:border-primary-border"
            placeholder="标签，用逗号分隔"
          />
          <div className="flex justify-end gap-1.5">
            <Button type="button" variant="secondary" disabled={editPending} onClick={onCancelEdit}>
              取消
            </Button>
            <Button type="button" variant="primary" disabled={editPending} onClick={() => onSaveMeta(item)}>
              {editPending ? '保存中...' : '保存备注'}
            </Button>
          </div>
        </div>
      )}
      <div className="mb-2.5 text-[11px] text-gray-300">{timeAgo(item.created_at)}</div>

      {item.target_type === 'content' && item.target_id && (
        <div className="mb-2.5 rounded-sm border border-primary-border bg-primary-light/40 p-2">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-black text-primary">
            <PenLine size={12} />
            生成创作方案
          </div>
          <div className="flex flex-wrap gap-1.5">
            {CREATION_PLATFORMS.map((platform) => {
              const Icon = platform.icon;
              const active = creatingKey === `${item.id}:${platform.id}`;
              const saved = Boolean(savedPlans[platform.id]);
              return (
                <div key={platform.id} className="flex gap-1">
                  <button
                    type="button"
                    disabled={Boolean(creatingKey)}
                    onClick={() => onGeneratePlan(item, platform.id)}
                    className={cx(
                      'inline-flex h-7 items-center gap-1 rounded-xs border px-2 text-[11px] font-black transition disabled:cursor-wait disabled:opacity-60',
                      active ? 'border-primary bg-primary text-white' : 'border-primary/20 bg-white text-primary hover:border-primary',
                    )}
                  >
                    <Icon size={12} />
                    {active ? '生成中' : platform.label}
                  </button>
                  {saved && (
                    <button
                      type="button"
                      disabled={Boolean(creatingKey)}
                      onClick={() => onOpenSavedPlan(item, platform.id)}
                      className="inline-flex h-7 items-center rounded-xs border border-gray-200 bg-white px-2 text-[11px] font-black text-gray-500 transition hover:border-primary-border hover:text-primary disabled:opacity-60"
                    >
                      上次
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        <select
          value={item.status}
          disabled={pending}
          onChange={(event) => onStatus(item, event.target.value as FavoriteStatus)}
          className="h-8 min-w-24 rounded-sm border border-gray-200 bg-white px-2 text-xs font-bold text-gray-600 outline-none disabled:cursor-wait disabled:opacity-60"
        >
          {STATUS_OPTIONS.filter((option) => option.value).map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        {item.target_type === 'content' && item.target_id && (
          <a
            href={`/topics/${item.target_id}`}
            className="inline-flex h-8 items-center gap-1 rounded-sm border border-gray-200 bg-white px-2 text-xs font-bold text-gray-500 hover:text-primary"
          >
            <FileText size={13} />
            详情
          </a>
        )}
        {item.target_type === 'book' && (
          <a
            href="/novel"
            className="inline-flex h-8 items-center gap-1 rounded-sm border border-gray-200 bg-white px-2 text-xs font-bold text-gray-500 hover:text-primary"
          >
            <BookOpen size={13} />
            榜单
          </a>
        )}
        {item.target_type === 'source' && (
          <a
            href="/admin/sources"
            className="inline-flex h-8 items-center gap-1 rounded-sm border border-gray-200 bg-white px-2 text-xs font-bold text-gray-500 hover:text-primary"
          >
            <Layers3 size={13} />
            信源
          </a>
        )}
        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-1 rounded-sm border border-gray-200 bg-white px-2 text-xs font-bold text-gray-500 hover:text-primary"
          >
            <ExternalLink size={13} />
            原文
          </a>
        )}
        <button
          type="button"
          disabled={pending}
          onClick={() => (editing ? onCancelEdit() : onStartEdit(item))}
          className="inline-flex h-8 items-center gap-1 rounded-sm border border-gray-200 bg-white px-2 text-xs font-bold text-gray-500 hover:text-primary disabled:cursor-wait disabled:opacity-60"
        >
          <PenLine size={13} />
          {editing ? '收起' : '备注'}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() => onRemove(item)}
          aria-label={item.status === 'archived' ? '删除收藏' : '归档收藏'}
          className="inline-flex h-8 items-center gap-1 rounded-sm border border-red-light bg-red-light px-2 text-xs font-bold text-red disabled:cursor-wait disabled:opacity-60"
          title="删除收藏"
        >
          {item.status === 'archived' ? <Archive size={13} /> : <Trash2 size={13} />}
        </button>
      </div>
    </article>
  );
}

/* ─── 内联子组件（从 page.tsx 抽离） ───────────────────────────────── */

/* ─── Header / Filter / Action / Error Bar 内联组件 ─────────────────────── */

export function HeaderStats({
  total,
  activeCount,
  counts,
}: {
  total: number;
  activeCount: number;
  counts: { byStatus: { inbox: number; researching: number; drafting: number; archived: number } };
}) {
  return (
    <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <Star size={20} className="text-primary" fill="currentColor" />
          <h1 className="m-0 text-[26px] font-black text-gray-900">收藏工作台</h1>
        </div>
        <p className="text-[13px] leading-6 text-gray-500">
          共 <b className="font-mono text-primary">{total}</b> 条收藏，当前筛选中 {activeCount} 条待推进
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:flex">
        <StatPill label="待处理" value={counts.byStatus.inbox} tone="amber" />
        <StatPill label="研究中" value={counts.byStatus.researching} tone="teal" />
        <StatPill label="创作中" value={counts.byStatus.drafting} tone="primary" />
        <StatPill label="已归档" value={counts.byStatus.archived} tone="neutral" />
      </div>
    </div>
  );
}

export function FiltersBar({
  targetType,
  setTargetType,
  status,
  setStatus,
  draftKeyword,
  setDraftKeyword,
  handleSearch,
  countsByType,
}: {
  targetType: FavoriteTargetType | '';
  setTargetType: (v: FavoriteTargetType | '') => void;
  status: FavoriteStatus | '';
  setStatus: (v: FavoriteStatus | '') => void;
  draftKeyword: string;
  setDraftKeyword: (v: string) => void;
  handleSearch: () => void;
  countsByType: Array<{ type: FavoriteTargetType; label: string; count: number }>;
}) {
  return (
    <Panel className="mb-4 p-3.5 shadow-sm">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Filter size={15} className="text-gray-400" />
          {TYPE_OPTIONS.map((option) => (
            <button
              key={option.value || 'all'}
              type="button"
              onClick={() => setTargetType(option.value)}
              aria-pressed={targetType === option.value}
              className={cx(
                'rounded-sm border px-3 py-1.5 text-xs font-bold transition',
                targetType === option.value
                  ? 'border-primary bg-primary-light text-primary'
                  : 'border-gray-200 bg-white text-gray-500 hover:text-gray-900',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as FavoriteStatus | '')}
            className="h-9 rounded-sm border border-gray-200 bg-white px-3 text-xs font-bold text-gray-600 outline-none focus:border-primary-border"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>{option.label}</option>
            ))}
          </select>
          <div className="flex min-w-0 items-center rounded-sm border border-gray-200 bg-white px-2 focus-within:border-primary-border">
            <Search size={14} className="shrink-0 text-gray-400" />
            <input
              value={draftKeyword}
              onChange={(event) => setDraftKeyword(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') handleSearch();
              }}
              className="h-8 min-w-0 bg-transparent px-2 text-xs outline-none"
              placeholder="搜索标题"
            />
            <button type="button" onClick={handleSearch} className="text-xs font-bold text-primary">
              搜索
            </button>
          </div>
        </div>
      </div>
      {countsByType.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t border-gray-100 pt-3">
          {countsByType.map((item) => (
            <Badge key={item.type} tone={TYPE_TONE[item.type]} className="rounded px-2 py-0.5">
              {item.label} {item.count}
            </Badge>
          ))}
        </div>
      )}
    </Panel>
  );
}

export function BatchActionBar({
  selectedCount,
  bulkPending,
  onMoveToStatus,
  onArchive,
  onRemove,
}: {
  selectedCount: number;
  bulkPending: boolean;
  onMoveToStatus: (status: FavoriteStatus) => void;
  onArchive: () => void;
  onRemove: () => void;
}) {
  if (selectedCount === 0) return null;
  return (
    <div className="sticky top-0 z-20 mb-4 flex flex-wrap items-center justify-between gap-3 rounded-sm border border-primary-border bg-white px-4 py-3 shadow-lg">
      <div className="flex items-center gap-2 text-[13px] font-black text-gray-900">
        <CheckSquare size={15} className="text-primary" />
        已选择 {selectedCount} 条素材
      </div>
      <div className="flex flex-wrap gap-2">
        {STATUS_FLOW.filter((column) => column.value !== 'archived').map((column) => (
          <Button
            key={column.value}
            type="button"
            variant="secondary"
            disabled={bulkPending}
            onClick={() => onMoveToStatus(column.value)}
          >
            移到{column.label}
          </Button>
        ))}
        <Button type="button" variant="secondary" disabled={bulkPending} onClick={onArchive}>
          <Archive size={13} />
          归档
        </Button>
        <Button type="button" variant="danger" disabled={bulkPending} onClick={onRemove}>
          <Trash2 size={13} />
          删除
        </Button>
      </div>
    </div>
  );
}

export function CreationDraftPanel({
  draft,
  platformLabel,
  onClose,
}: {
  draft: { item: { title: string }; platform: string; plan: unknown };
  platformLabel: string;
  onClose: () => void;
}) {
  // 类型断言：plan 实际是 CreationPlan，但本组件仅做展示不引用字段，避免循环依赖
  const plan = draft.plan as Parameters<typeof import('@/components/CreationPlanDisplay').default>[0]['plan'];
  return (
    <Panel className="mb-4 overflow-hidden p-0 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <Badge tone="primary" className="rounded px-2 py-0.5">创作方案</Badge>
            <span className="text-xs font-bold text-gray-400">{platformLabel}</span>
          </div>
          <div className="line-clamp-1 text-sm font-black text-gray-900">{draft.item.title}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭创作方案"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-xs border border-gray-200 bg-white text-gray-400 transition hover:text-gray-800"
          title="关闭"
        >
          <X size={15} />
        </button>
      </div>
      <div className="bg-gray-50 px-4 py-4">
        <CreationPlanDisplay plan={plan} platform={draft.platform} />
      </div>
    </Panel>
  );
}

export function ErrorBanner({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  if (!error) return null;
  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-sm border border-red/20 bg-red-light px-4 py-3 text-[13px] text-red">
      <div className="flex min-w-0 items-center gap-2">
        <AlertCircle size={15} className="shrink-0" />
        <span className="break-words">{error}</span>
      </div>
      <Button type="button" variant="danger" onClick={onRetry}>
        <RefreshCw size={13} />
        重试
      </Button>
    </div>
  );
}

export function DirtyStatusBar({
  dirtyCount,
  savedNotice,
  saving,
  onDiscard,
  onSave,
}: {
  dirtyCount: number;
  savedNotice: string | null;
  saving: boolean;
  onDiscard: () => void;
  onSave: () => void;
}) {
  if (dirtyCount === 0 && !savedNotice) return null;
  const dirty = dirtyCount > 0;
  return (
    <div
      className={cx(
        'mb-4 flex flex-wrap items-center justify-between gap-3 rounded-sm border px-4 py-3 text-[13px]',
        dirty ? 'border-amber-border bg-amber-light text-amber' : 'border-teal-border bg-teal-light text-teal',
      )}
    >
      <div className="font-black">
        {dirty ? `有 ${dirtyCount} 个状态列的排序未保存` : savedNotice}
      </div>
      {dirty && (
        <div className="flex gap-2">
          <Button type="button" variant="secondary" disabled={saving} onClick={onDiscard}>
            撤销
          </Button>
          <Button type="button" variant="primary" disabled={saving} onClick={onSave}>
            {saving ? '保存中...' : '保存排序'}
          </Button>
        </div>
      )}
    </div>
  );
}

export function BoardGrid({
  loading,
  items,
  boardColumns,
  selectedIds,
  pendingId,
  editingId,
  editNote,
  editTags,
  editPending,
  creatingKey,
  draggingId,
  dropTarget,
  dragEnabled,
  onSelectColumn,
  onSelect,
  onStatus,
  onRemove,
  onGeneratePlan,
  onOpenSavedPlan,
  onStartEdit,
  onCancelEdit,
  onEditNote,
  onEditTags,
  onSaveMeta,
  onDragStart,
  onDragHover,
  onDragEnd,
  onMove,
}: {
  loading: boolean;
  items: FavoriteItem[];
  boardColumns: StatusFlowColumn[];
  selectedIds: Set<number>;
  pendingId: number | null;
  editingId: number | null;
  editNote: string;
  editTags: string;
  editPending: boolean;
  creatingKey: string | null;
  draggingId: number | null;
  dropTarget: { status: FavoriteStatus; beforeId: number | null } | null;
  dragEnabled: boolean;
  onSelectColumn: (items: FavoriteItem[]) => void;
  onSelect: (id: number) => void;
  onStatus: (item: FavoriteItem, status: FavoriteStatus) => void;
  onRemove: (item: FavoriteItem) => void;
  onGeneratePlan: (item: FavoriteItem, platform: string) => void;
  onOpenSavedPlan: (item: FavoriteItem, platform: string) => void;
  onStartEdit: (item: FavoriteItem) => void;
  onCancelEdit: () => void;
  onEditNote: (value: string) => void;
  onEditTags: (value: string) => void;
  onSaveMeta: (item: FavoriteItem) => void;
  onDragStart: (id: number) => void;
  onDragHover: (target: { status: FavoriteStatus; beforeId: number | null } | null) => void;
  onDragEnd: () => void;
  onMove: (itemId: number, status: FavoriteStatus, beforeId: number | null) => void;
}) {
  if (loading) {
    return <div className="p-20 text-center text-sm text-gray-400">加载中...</div>;
  }
  if (items.length === 0) {
    return (
      <div className="p-20 text-center text-sm text-gray-400">
        <Inbox size={38} className="mx-auto mb-4 text-gray-300 opacity-70" strokeWidth={1.8} />
        <div>当前筛选下没有收藏</div>
        <div className="mt-1 text-xs">从内容、榜单、信源或趋势入口加入收藏后会出现在这里</div>
      </div>
    );
  }
  return (
    <div className="grid gap-3 pb-10 lg:grid-cols-2 2xl:grid-cols-4">
      {boardColumns.map((column) => (
        <FavoriteColumn
          key={column.value}
          column={column}
          selectedIds={selectedIds}
          pendingId={pendingId}
          onSelectColumn={onSelectColumn}
          onSelect={onSelect}
          onStatus={onStatus}
          onRemove={onRemove}
          onGeneratePlan={onGeneratePlan}
          onOpenSavedPlan={onOpenSavedPlan}
          creatingKey={creatingKey}
          editingId={editingId}
          editNote={editNote}
          editTags={editTags}
          editPending={editPending}
          onStartEdit={onStartEdit}
          onCancelEdit={onCancelEdit}
          onEditNote={onEditNote}
          onEditTags={onEditTags}
          onSaveMeta={onSaveMeta}
          draggingId={draggingId}
          dropTarget={dropTarget}
          dragEnabled={dragEnabled}
          onDragStart={onDragStart}
          onDragHover={onDragHover}
          onDragEnd={onDragEnd}
          onMove={onMove}
        />
      ))}
    </div>
  );
}
