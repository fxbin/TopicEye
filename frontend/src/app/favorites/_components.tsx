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
  Archive,
  BookOpen,
  CheckSquare,
  ExternalLink,
  FileText,
  GripVertical,
  Layers3,
  PenLine,
  Square,
  Trash2,
} from 'lucide-react';
import type { FavoriteItem, FavoriteStatus } from '@/types';
import { Badge, Button, cx } from '@/components/ui';
import { timeAgo } from '@/lib/datetime';
import {
  CREATION_PLATFORMS,
  STATUS_LABEL,
  STATUS_OPTIONS,
  TYPE_LABEL,
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
            href="/sources"
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
          className="inline-flex h-8 items-center gap-1 rounded-sm border border-red-light bg-red-light px-2 text-xs font-bold text-red disabled:cursor-wait disabled:opacity-60"
          title="删除收藏"
        >
          {item.status === 'archived' ? <Archive size={13} /> : <Trash2 size={13} />}
        </button>
      </div>
    </article>
  );
}