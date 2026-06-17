'use client';

import React, { useState } from 'react';
import { ChevronDown, Star } from 'lucide-react';
import { Button, cx } from '@/components/ui';
import { timeAgo } from '@/lib/utils';

export interface BackendSource {
  id: number;
  name: string;
  source_type: string;
  url: string;
  keyword?: string | null;
  platform?: string;
  category: string;
  weight: number;
  sort_order?: number;
  fetch_interval_minutes: number;
  status: string;
  last_sync_at: string | null;
  sync_error: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

const typeColors: Record<string, string> = {
  RSS: 'bg-purple-light text-purple',
  RSSHub: 'bg-teal-light text-teal',
  API: 'bg-primary-light text-primary',
  公众号: 'bg-red-light text-red',
  网站: 'bg-amber-light text-amber',
};

const INTERVAL_OPTIONS = [
  { value: 30, label: '30分钟' },
  { value: 60, label: '1小时' },
  { value: 120, label: '2小时' },
  { value: 360, label: '6小时' },
  { value: 720, label: '12小时' },
  { value: 1440, label: '1天' },
];

const SENSITIVE_QUERY_KEYS = new Set([
  'access_token',
  'apikey',
  'api_key',
  'auth_token',
  'authorization',
  'client_secret',
  'key',
  'password',
  'secret',
  'token',
]);

function formatInterval(minutes: number): string {
  const opt = INTERVAL_OPTIONS.find((o) => o.value === minutes);
  return opt ? opt.label : `${minutes}分钟`;
}

function redactSourceUrlForDisplay(value: string): string {
  try {
    const url = new URL(value);
    let changed = false;
    url.searchParams.forEach((_, key) => {
      if (SENSITIVE_QUERY_KEYS.has(key.toLowerCase())) {
        url.searchParams.set(key, '***');
        changed = true;
      }
    });
    return changed ? url.toString() : value;
  } catch {
    return value.replace(
      /([?&](?:access_token|apikey|api_key|auth_token|authorization|client_secret|key|password|secret|token)=)[^&#\s]+/gi,
      '$1***',
    );
  }
}

function Spinner() {
  return <div className="h-[18px] w-[18px] animate-spin rounded-full border-2 border-gray-200 border-t-primary" />;
}

interface SourceRowProps {
  source: BackendSource;
  syncing: boolean;
  syncResult: string | null;
  deleting: boolean;
  onSync: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onWeightChange?: (w: number) => void;
  onIntervalChange?: (minutes: number) => void;
  favorite?: boolean;
  favoritePending?: boolean;
  onFavorite?: () => void;
  selected?: boolean;
  onSelect?: (source: BackendSource, checked: boolean) => void;
}

export default function SourceRowComponent({
  source,
  syncing,
  syncResult,
  deleting,
  onSync,
  onEdit,
  onDelete,
  onWeightChange,
  onIntervalChange,
  favorite = false,
  favoritePending = false,
  onFavorite,
  selected = false,
  onSelect,
}: SourceRowProps) {
  const [intervalOpen, setIntervalOpen] = useState(false);
  const typeClass = typeColors[source.source_type] || 'bg-gray-100 text-gray-600';
  const isActive = source.status === 'active' && source.enabled;
  const sourceSyncing = syncing || source.status === 'syncing';
  const sourceDisabled = !source.enabled || source.status === 'disabled';
  const syncDisabled = sourceSyncing || sourceDisabled;
  const displayUrl = source.url ? redactSourceUrlForDisplay(source.url) : '';

  return (
    <div
      onMouseLeave={() => setIntervalOpen(false)}
      className={cx(
        'grid grid-cols-[auto_2fr_1fr_1fr_1.2fr_1fr_1fr_0.8fr_1.5fr] items-center border-b border-gray-100 bg-white px-6 py-3.5 text-[13px] text-gray-700 transition hover:bg-gray-50',
        deleting && 'opacity-50',
      )}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={(e) => onSelect?.(source, e.target.checked)}
        onClick={(e) => e.stopPropagation()}
        className="h-4 w-4 cursor-pointer rounded border-gray-300 text-orange focus:ring-orange"
      />
      <div className="min-w-0">
        <span className="font-bold">{source.name}</span>
        {displayUrl && (
          <div className="mt-0.5 max-w-[220px] truncate text-[11px] text-gray-400" title={displayUrl}>
            {displayUrl}
          </div>
        )}
      </div>

      <span className={cx('w-fit rounded px-2 py-0.5 text-[11px] font-bold', typeClass)}>{source.source_type}</span>
      <span className="text-gray-500">{source.category}</span>

      <div className="min-w-0">
        <span className={cx('text-xs', source.sync_error ? 'text-red' : 'text-gray-400')}>
          {sourceSyncing ? '同步中' : source.sync_error ? '同步失败' : timeAgo(source.last_sync_at)}
        </span>
        {source.sync_error && <div className="mt-0.5 truncate text-[11px] text-red">{source.sync_error}</div>}
        {syncResult && <div className="mt-0.5 truncate text-[11px] text-teal">{syncResult}</div>}
      </div>

      <div className="relative">
        <button
          type="button"
          onClick={() => setIntervalOpen((v) => !v)}
          className={cx(
            'whitespace-nowrap rounded border px-2 py-1 text-[11px] transition',
            intervalOpen ? 'border-primary-border bg-primary-light text-primary' : 'border-gray-200 bg-gray-100 text-gray-600',
          )}
          title="点击修改采集频率"
        >
          {formatInterval(source.fetch_interval_minutes)}
          <ChevronDown size={12} strokeWidth={2} className="ml-1 inline opacity-70" />
        </button>
        {intervalOpen && (
          <div className="absolute left-0 top-[calc(100%+4px)] z-50 min-w-[90px] rounded-xs border border-gray-200 bg-white p-1 shadow-[0_4px_12px_rgba(0,0,0,0.08)]">
            {INTERVAL_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onIntervalChange?.(opt.value);
                  setIntervalOpen(false);
                }}
                className={cx(
                  'block w-full rounded px-2.5 py-1.5 text-left text-xs transition hover:bg-gray-50',
                  opt.value === source.fetch_interval_minutes ? 'bg-primary-light font-bold text-primary' : 'text-gray-700',
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex cursor-pointer items-center gap-0.5" title={`权重 ${source.weight}/5 — 影响精选加分：${source.weight > 3 ? '+' : ''}${(source.weight - 3) * 8} 分`}>
        {[1, 2, 3, 4, 5].map((w) => (
          <button
            key={w}
            type="button"
            onClick={() => onWeightChange?.(w)}
            className={cx('text-[11px] transition', w <= source.weight ? 'text-primary' : 'text-gray-200')}
          >
            ●
          </button>
        ))}
        <span className="ml-1 text-[10px] text-gray-400">{(source.weight - 3) * 8 > 0 ? '+' : ''}{(source.weight - 3) * 8}</span>
      </div>

      <div className="flex items-center gap-1.5">
        <span className={cx('h-2 w-2 rounded-full', isActive ? 'bg-teal' : 'bg-red')} />
        <span className={cx('text-[11px]', isActive ? 'text-teal' : 'text-red')}>
          {source.enabled ? (source.status === 'active' ? '正常' : source.status) : '已禁用'}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {onFavorite && (
          <button
            type="button"
            onClick={onFavorite}
            disabled={favoritePending}
            className={cx(
              'inline-flex h-7 w-7 items-center justify-center rounded-sm border transition disabled:cursor-wait disabled:opacity-60',
              favorite ? 'border-amber-border bg-amber-light text-amber' : 'border-gray-200 bg-white text-gray-300 hover:text-amber',
            )}
            title={favorite ? '移出收藏' : '收藏信源'}
          >
            <Star size={13} fill={favorite ? 'currentColor' : 'none'} />
          </button>
        )}
        <Button
          type="button"
          onClick={onSync}
          disabled={syncDisabled}
          variant={sourceSyncing ? 'secondary' : 'success'}
          className="min-h-7 px-2.5 py-1 text-[11px]"
          title={sourceDisabled ? '信源已禁用，启用后可同步' : '同步信源'}
        >
          {sourceSyncing ? <Spinner /> : null}
          {sourceSyncing ? '同步中' : '同步'}
        </Button>
        <Button type="button" onClick={onEdit} variant="secondary" className="min-h-7 bg-purple-light px-2.5 py-1 text-[11px] text-purple hover:text-purple">
          编辑
        </Button>
        <Button type="button" onClick={onDelete} disabled={deleting} variant="ghost" className="min-h-7 px-2.5 py-1 text-[11px] text-red hover:text-red">
          {deleting ? '删除中…' : '删除'}
        </Button>
      </div>
    </div>
  );
}

export { Spinner };
