'use client';

/**
 * Sources page 内联子面板（从 page.tsx 抽出）。
 *
 * - RSSHubManager   RSSHub 实例管理面板（列表/启用禁用/添加/删除）
 * - SourceListPanel 信源列表表格 + 分页器
 */

import React, { useEffect, useState } from 'react';
import { Button, Panel, cx } from '@/components/ui';
import { Spinner } from '@/components/SourceRow';
import SourceRowComponent, { type BackendSource } from '@/components/SourceRow';
import type { RSSHubInstance } from '@/types/stats';
import { getFavoriteTargetKey } from '@/lib/favorites';
import { settingsApi } from '@/lib/api';

export function RSSHubManager({
  instances,
  loading,
  saving,
  newInstanceUrl,
  setNewInstanceUrl,
  onToggle,
  onDelete,
  onAdd,
}: {
  instances: RSSHubInstance[];
  loading: boolean;
  saving: boolean;
  newInstanceUrl: string;
  setNewInstanceUrl: (v: string) => void;
  onToggle: (url: string) => void;
  onDelete: (url: string) => void;
  onAdd: () => void;
}) {
  return (
    <Panel className="mb-5 p-5">
      <div className="mb-3.5 flex items-center justify-between gap-3">
        <div>
          <h2 className="mb-0.5 text-[15px] font-black text-gray-800">RSSHub 实例</h2>
          <p className="text-xs text-gray-400">按优先级顺序尝试，禁用则跳过。添加小红书/微博/B站等路由时使用。</p>
        </div>
        {saving && <span className="text-xs text-gray-400">保存中…</span>}
      </div>

      <div className="mb-3 flex flex-col gap-2">
        {loading ? (
          <div className="py-2 text-[13px] text-gray-400">加载中…</div>
        ) : instances.length === 0 ? (
          <div className="py-2 text-[13px] text-gray-400">暂无实例</div>
        ) : (
          instances.map((inst, idx) => (
            <div key={inst.url} className="flex items-center gap-2.5 rounded-sm border border-gray-100 bg-gray-50 px-3 py-2">
              <span className="min-w-4 font-mono text-[11px] text-gray-300">#{idx + 1}</span>
              <span className={cx('flex-1 break-all font-mono text-[13px]', inst.enabled ? 'text-gray-800' : 'text-gray-400')}>{inst.url}</span>
              {inst.note && <span className="text-[11px] text-gray-400">{inst.note}</span>}
              <button
                type="button"
                onClick={() => onToggle(inst.url)}
                disabled={saving}
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
                onClick={() => onDelete(inst.url)}
                disabled={saving}
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
          onKeyDown={(e) => e.key === 'Enter' && onAdd()}
          placeholder="https://rsshub.example.com"
          className="h-9 flex-1 rounded-sm border border-gray-200 px-3 font-mono text-[13px] outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light"
        />
        <Button type="button" variant="primary" onClick={onAdd} disabled={saving || !newInstanceUrl.trim()}>
          + 添加实例
        </Button>
      </div>
    </Panel>
  );
}

export function SourceListPanel({
  loading,
  sources,
  syncingIds,
  syncResults,
  deletingIds,
  total,
  page,
  pageSize,
  favoriteTargets,
  favoriteTargetPendingKeys,
  sourceFavoriteKeys,
  selectedIds,
  onSync,
  onEdit,
  onDelete,
  onWeightChange,
  onIntervalChange,
  onFavorite,
  onSelect,
  onPageChange,
}: {
  loading: boolean;
  sources: BackendSource[];
  syncingIds: Set<number>;
  syncResults: Record<number, string>;
  deletingIds: Set<number>;
  total: number;
  page: number;
  pageSize: number;
  favoriteTargets: Set<string>;
  favoriteTargetPendingKeys: Set<string>;
  sourceFavoriteKeys: Set<string>;
  selectedIds: Set<number>;
  onSync: (id: number) => void;
  onEdit: (source: BackendSource) => void;
  onDelete: (id: number) => void;
  onWeightChange: (id: number, weight: number) => void;
  onIntervalChange: (id: number, mins: number) => void;
  onFavorite: (source: BackendSource) => void;
  onSelect: (source: BackendSource, checked: boolean) => void;
  onPageChange: (p: number) => void;
}) {
  return (
    <>
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
          {sources.map((src) => {
            const favKey = getFavoriteTargetKey({ target_type: 'source', target_id: src.id });
            return (
              <SourceRowComponent
                key={src.id}
                source={src}
                syncing={syncingIds.has(src.id)}
                syncResult={syncResults[src.id] || null}
                deleting={deletingIds.has(src.id)}
                onSync={() => onSync(src.id)}
                onEdit={() => onEdit(src)}
                onDelete={() => onDelete(src.id)}
                onWeightChange={(w) => onWeightChange(src.id, w)}
                onIntervalChange={(mins) => onIntervalChange(src.id, mins)}
                favorite={favoriteTargets.has(favKey) || sourceFavoriteKeys.has(favKey)}
                favoritePending={favoriteTargetPendingKeys.has(favKey)}
                onFavorite={() => onFavorite(src)}
                selected={selectedIds.has(src.id)}
                onSelect={onSelect}
              />
            );
          })}
        </Panel>
      )}

      {/* Pagination */}
      {total > pageSize && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 py-3 text-[13px] text-gray-500">
          <span>
            第 {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} 条，共 {total} 条
          </span>
          <div className="flex flex-wrap gap-1.5">
            <Button type="button" variant="secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)} className="min-h-8 px-3.5 py-1.5 text-[13px] disabled:cursor-not-allowed">
              上一页
            </Button>
            {Array.from({ length: Math.ceil(total / pageSize) }, (_, i) => i + 1)
              .filter((p) => {
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
                      onClick={() => onPageChange(p)}
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
              onClick={() => onPageChange(page + 1)}
              className="min-h-8 px-3.5 py-1.5 text-[13px] disabled:cursor-not-allowed"
            >
              下一页
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

// ── Feature flags 面板（管理员后台一键开关功能模块）──

const FEATURE_LABELS: Record<string, { label: string; description: string }> = {
  webnovel_module: {
    label: '网文雷达',
    description: '番茄/七猫/知乎盐选等国内网文榜单。默认关闭以保持国际化体验干净，按需开启。',
  },
};

export function FeatureFlagsPanel({ onUpdate }: { onUpdate?: (flags: Record<string, boolean>) => void }) {
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await settingsApi.getFeatureFlags();
        if (!cancelled) setFlags(data.flags || {});
      } catch {
        // 非管理员或端点不可用，静默
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const toggle = async (key: string) => {
    const next = !flags[key];
    setSavingKey(key);
    try {
      const { flags: merged } = await settingsApi.updateFeatureFlags({ [key]: next });
      setFlags(merged);
      onUpdate?.(merged);  // 同步全局 enabledFeatures → 菜单/路由守卫实时刷新
    } catch {
      // 失败回滚由用户重试
    } finally {
      setSavingKey(null);
    }
  };

  const entries = Object.entries(flags);
  return (
    <Panel className="mb-5 p-5">
      <div className="mb-3.5">
        <h2 className="mb-0.5 text-[15px] font-black text-gray-800">功能模块开关</h2>
        <p className="text-xs text-gray-400">按需启用/禁用功能模块。关闭后菜单和接口同步隐藏，开启后立即生效。</p>
      </div>
      {loading ? (
        <div className="py-2 text-[13px] text-gray-400">加载中…</div>
      ) : entries.length === 0 ? (
        <div className="py-2 text-[13px] text-gray-400">暂无可配置的功能模块</div>
      ) : (
        <div className="flex flex-col gap-2">
          {entries.map(([key, enabled]) => {
            const meta = FEATURE_LABELS[key] || { label: key, description: '' };
            const isSaving = savingKey === key;
            return (
              <div key={key} className="flex items-center gap-3 rounded-sm border border-gray-100 bg-gray-50 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold text-gray-800">{meta.label}</div>
                  {meta.description && <div className="mt-0.5 text-[11px] leading-5 text-gray-500">{meta.description}</div>}
                </div>
                <button
                  type="button"
                  onClick={() => toggle(key)}
                  disabled={isSaving}
                  className={cx(
                    'relative h-6 w-11 shrink-0 rounded-full transition disabled:cursor-wait disabled:opacity-60',
                    enabled ? 'bg-primary' : 'bg-gray-300',
                  )}
                  title={enabled ? '点击关闭' : '点击开启'}
                >
                  <span
                    className={cx(
                      'absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all',
                      enabled ? 'left-[22px]' : 'left-0.5',
                    )}
                  />
                </button>
                <span className={cx('w-10 text-[11px] font-black', enabled ? 'text-primary' : 'text-gray-400')}>
                  {isSaving ? '...' : enabled ? '已启用' : '已关闭'}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}