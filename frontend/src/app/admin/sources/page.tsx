'use client';

/**
 * 信源管理（S5 切片，#121 后台改版）。
 *
 * 列表视图由手写 grid 迁移到 AdminTable（三态内建：骨架 / 内联错误+重试 / 空态），
 * 高频动作（同步 / 编辑）直接可见，其余收进行尾「···」菜单；
 * 删除 / 暂停类破坏性动作统一走二次确认弹窗（替代原生 confirm）。
 * 筛选换 AdminFilters（搜索 300ms 防抖）+ AdminFilterChips（单移除 / 清空全部）。
 * 筛选 / 搜索 / 页码 / 每页条数 / 视图与 URL query 双向同步（四页试点之一）。
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  FileSearch,
  List,
  MoreHorizontal,
  Network,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  Star,
  Trash2,
  Upload,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { favoritesApi, settingsApi, sourcesApi } from '@/lib/api';
import type { CreateSourceRequest, RSSHubInstance, SourceBatchImportItem, UpdateSourceRequest } from '@/lib/api';
import { useAppContext } from '@/components/ClientLayout';
import { timeAgo } from '@/lib/utils';
import { Badge, Button, PanelTitle, cx } from '@/components/ui';
import { AdminModal, AdminModalFooter, AdminNoticeBanner, AdminPageHeader, AdminPageShell } from '@/components/admin-ui';
import { AdminEmptyState, AdminFilterChips, AdminFilters, AdminTable, toast } from '@/components/admin';
import type { AdminFilterChip, AdminTableColumn } from '@/components/admin';
import { Pagination } from '@/components/Pagination';
import { emptyForm } from '@/components/SourceForm';
import type { FormState } from '@/components/SourceForm';
import { Spinner } from '@/components/SourceRow';
import type { BackendSource } from '@/components/SourceRow';
import SourceSyncBoard from '@/components/SourceSyncBoard';
import { buildSourceSyncBoard, sourceTypeLabel } from '@/lib/source-sync-board';
import { getFavoriteTargetKey } from '@/lib/favorites';
import { EvidenceProfileModal } from '@/components/EvidenceProfileModal';
import {
  type SourceTierKey,
  getSourceTier,
  normalizeRsshubInstanceUrl,
  validateApiSourceConfig,
} from './_sources-utils';

import { SourceMapView } from './_components';
import { AddSourceModal, BatchImportModal, EditSourceModal } from './_modals';
import { RSSHubManager, FeatureFlagsPanel } from './_panels';
import { describeBatchResult, recomputeSelectionAfterBatch, runBatchToggle } from './_batch-utils';

// ─── 常量 ───

const SOURCE_TYPE_FILTERS = ['RSS', 'RSSHub', 'TwitterRSS', 'Reddit', 'API', 'Zhihu', '网站'] as const;

const TYPE_BADGE_TONE: Record<string, 'neutral' | 'primary' | 'teal' | 'amber' | 'purple'> = {
  RSS: 'purple',
  RSSHub: 'teal',
  API: 'primary',
  网站: 'amber',
};

const INTERVAL_OPTIONS = [
  { value: 30, label: '30分钟' },
  { value: 60, label: '1小时' },
  { value: 120, label: '2小时' },
  { value: 360, label: '6小时' },
  { value: 720, label: '12小时' },
  { value: 1440, label: '1天' },
];

const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [10, 20, 50] as const;

// ─── URL query 同步（#121 四页试点之一）──
// 挂载时从 location.search 恢复初始状态；此后筛选/搜索/页码/每页条数变化用
// history.replaceState 覆写 query——不产生历史记录、不触发导航，
// 刻意不用 useSearchParams 以避开 Suspense 边界（与 contents 页同口径）。
// 默认值（第 1 页、每页 20、无筛选、地图视图）不写入 query，保持 URL 干净。

type SourcesQueryState = {
  page: number;
  pageSize: number;
  q: string;
  type: string;
  enabled: boolean | undefined;
  view: 'map' | 'sync' | 'list';
};

function defaultSourcesQueryState(): SourcesQueryState {
  return {
    page: 1,
    pageSize: DEFAULT_PAGE_SIZE,
    q: '',
    type: '',
    enabled: undefined,
    view: 'map',
  };
}

function readInitialStateFromLocation(): SourcesQueryState {
  const defaults = defaultSourcesQueryState();
  const sp = new URLSearchParams(window.location.search);
  const page = Math.max(1, Number.parseInt(sp.get('page') ?? '', 10) || 1);
  const rawPageSize = Number.parseInt(sp.get('page_size') ?? '', 10);
  const pageSize = (PAGE_SIZE_OPTIONS as readonly number[]).includes(rawPageSize)
    ? rawPageSize
    : DEFAULT_PAGE_SIZE;
  const rawType = sp.get('type') ?? '';
  const type = (SOURCE_TYPE_FILTERS as readonly string[]).includes(rawType) ? rawType : '';
  const enabledParam = sp.get('enabled');
  const view = sp.get('view');
  return {
    page,
    pageSize,
    q: sp.get('q') ?? '',
    type,
    enabled: enabledParam === '1' ? true : enabledParam === '0' ? false : undefined,
    view: view === 'sync' || view === 'list' ? view : 'map',
  };
}

// ─── URL 展示打码（与 SourceRow 同口径，纯展示层）──
// 信源 URL 常带 token/key 类 query 参数，展示前统一换成 ***。

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

// ─── 行尾「···」菜单 ───
// 高频动作（≤2 个）之外的行操作收进这里。键盘可达：打开后焦点移入首项，
// ↑/↓ 在菜单项间移动，Esc 关闭并还焦给触发按钮，点击菜单外任意处关闭。
// 菜单用 fixed 定位挂在视口坐标上——否则会被表格 overflow-x-auto 滚动容器裁剪。

interface RowMenuItem {
  key: string;
  label: string;
  icon: LucideIcon;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

function RowActionsMenu({ label, items }: { label: string; items: RowMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  const openMenu = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPos({ top: rect.bottom + 4, left: rect.right });
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    // 打开后把焦点移进菜单，键盘用户不用再 Tab 一次
    const frame = window.requestAnimationFrame(() => {
      menuRef.current
        ?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')
        ?.focus();
    });
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    // 任何滚动/缩放都收回菜单：fixed 菜单不跟随滚动，悬空比关闭更糟
    const close = () => setOpen(false);
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (open ? setOpen(false) : openMenu())}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        className="flex h-7 w-7 items-center justify-center rounded-xs border border-transparent text-ink-500 transition hover:border-ink-200 hover:bg-white hover:text-ink-900"
      >
        <MoreHorizontal size={15} strokeWidth={2} />
      </button>
      {open && pos && (
        <div
          ref={menuRef}
          role="menu"
          aria-label={label}
          style={{ position: 'fixed', top: pos.top, left: pos.left, transform: 'translateX(-100%)' }}
          className="z-50 min-w-[148px] rounded-xs border border-ink-200 bg-white p-1 shadow-[0_8px_24px_rgba(15,23,42,0.12)]"
          onKeyDown={(event) => {
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
            event.preventDefault();
            const buttons = Array.from(
              menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [],
            );
            if (buttons.length === 0) return;
            const activeIndex = buttons.findIndex((button) => button === document.activeElement);
            const nextIndex =
              event.key === 'ArrowDown'
                ? (activeIndex + 1) % buttons.length
                : (activeIndex - 1 + buttons.length) % buttons.length;
            buttons[nextIndex]?.focus();
          }}
        >
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
                className={cx(
                  'flex w-full items-center gap-2 rounded-xs px-2.5 py-1.5 text-left text-xs transition disabled:cursor-not-allowed disabled:opacity-50',
                  item.danger ? 'text-red-600 hover:bg-red-light' : 'text-ink-700 hover:bg-ink-100',
                )}
              >
                <Icon size={13} strokeWidth={2} aria-hidden="true" />
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── 破坏性动作二次确认 ───
// 删除 / 暂停（禁用类）统一收口到这一个确认弹窗，替代原生 confirm()。

interface ConfirmState {
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  onConfirm: () => void | Promise<void>;
}

// ─── Page Component ───

export default function SourcesPage() {
  const { currentUser, updateEnabledFeatures, favoriteTargets, favoriteTargetPendingKeys, toggleFavoriteTarget, refreshCounts } = useAppContext();
  // 两段式恢复：SSR 与首帧一律用默认值（防 hydration mismatch——惰性读
  // location 会在带参数直达时让服务端/客户端首帧不一致），挂载后再从 URL
  // 恢复一次；didRestore 门让首拉只发一次且 URL 不被默认值覆写清掉。
  const [initial] = useState(defaultSourcesQueryState);
  const [sources, setSources] = useState<BackendSource[]>([]);
  const [mapSources, setMapSources] = useState<BackendSource[]>([]);
  const [sourceFavoriteKeys, setSourceFavoriteKeys] = useState<Set<string>>(new Set());
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(initial.pageSize);
  const [viewMode, setViewMode] = useState<'map' | 'sync' | 'list'>(initial.view);
  const [searchKeyword, setSearchKeyword] = useState(initial.q);
  const [searchResetKey, setSearchResetKey] = useState(0);
  const [filterType, setFilterType] = useState(initial.type);
  const [filterEnabled, setFilterEnabled] = useState<boolean | undefined>(initial.enabled);
  const [loading, setLoading] = useState(true);
  // 列表加载失败 → AdminTable 内联错误 + 重试；系统级/变更类错误仍走顶部 AdminNoticeBanner
  const [listError, setListError] = useState<string | null>(null);
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
  const [importingOPML, setImportingOPML] = useState(false);
  const [showBatchImport, setShowBatchImport] = useState(false);
  const [evidenceProfileSource, setEvidenceProfileSource] = useState<BackendSource | null>(null);
  const [batchImportContent, setBatchImportContent] = useState('');
  const [batchImportCategory, setBatchImportCategory] = useState('批量导入');
  const [batchImportPreview, setBatchImportPreview] = useState<SourceBatchImportItem[]>([]);
  const [batchImportPreviewing, setBatchImportPreviewing] = useState(false);
  const [batchImporting, setBatchImporting] = useState(false);
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // ─── Fetch sources ───
  const fetchSources = useCallback(async (p: number = 1): Promise<boolean> => {
    try {
      setLoading(true);
      setListError(null);
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
      setListError(err instanceof Error ? err.message : '加载信源列表失败');
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

  // 挂载后恢复 URL 状态（两段式的第二段），随后放行首拉
  const [didRestore, setDidRestore] = useState(false);
  useEffect(() => {
    const restored = readInitialStateFromLocation();
    if (restored.page !== initial.page) setPage(restored.page);
    if (restored.pageSize !== initial.pageSize) setPageSize(restored.pageSize);
    if (restored.view !== initial.view) setViewMode(restored.view);
    if (restored.q !== initial.q) setSearchKeyword(restored.q);
    if (restored.type !== initial.type) setFilterType(restored.type);
    if (restored.enabled !== initial.enabled) setFilterEnabled(restored.enabled);
    setDidRestore(true);
    // 仅挂载时执行一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 首拉与筛选/每页条数变化的重拉。翻页不进这个 effect（由分页器直接调
  // fetchSources），避免翻一个页码连带全量信源地图重拉。
  useEffect(() => {
    if (!didRestore) return;
    void fetchSources(page);
    void fetchSourceMap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [didRestore, fetchSources, fetchSourceMap]);

  // RSSHub 实例不随筛选变化，只在挂载时拉一次
  useEffect(() => {
    fetchRSSHubInstances();
  }, [fetchRSSHubInstances]);

  // URL query 覆写：与恢复逻辑对称，非默认值才落 query（恢复完成前不写，
  // 防止把直达 URL 清成默认态）
  useEffect(() => {
    if (!didRestore) return;
    const sp = new URLSearchParams();
    if (searchKeyword.trim()) sp.set('q', searchKeyword.trim());
    if (filterType) sp.set('type', filterType);
    if (filterEnabled !== undefined) sp.set('enabled', filterEnabled ? '1' : '0');
    if (page > 1) sp.set('page', String(page));
    if (pageSize !== DEFAULT_PAGE_SIZE) sp.set('page_size', String(pageSize));
    if (viewMode !== 'map') sp.set('view', viewMode);
    const qs = sp.toString();
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
  }, [didRestore, searchKeyword, filterType, filterEnabled, page, pageSize, viewMode]);

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

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // 恢复的页码可能越过当前筛选下的总页数（书签里存着 page=99），收回最后一页
  useEffect(() => {
    if (!loading && page > totalPages) void fetchSources(totalPages);
  }, [loading, page, totalPages, fetchSources]);

  // ─── 确认弹窗执行 ───
  const runConfirm = async () => {
    if (!confirmState || confirmBusy) return;
    setConfirmBusy(true);
    try {
      await confirmState.onConfirm();
      setConfirmState(null);
    } catch {
      // 各 onConfirm 自带错误上抛（AdminNoticeBanner），这里只防止确认框卡死
    } finally {
      setConfirmBusy(false);
    }
  };

  // ─── Toggle instance enabled ───
  const toggleInstance = async (url: string) => {
    const target = rsshubInstances.find((i) => i.url === url);
    const updated = rsshubInstances.map((i) =>
      i.url === url ? { ...i, enabled: !i.enabled } : i
    );
    setRsshubInstances(updated);
    try {
      setRsshubSaving(true);
      await settingsApi.updateRSSHubInstances(updated);
      toast.success(`实例已${target?.enabled ? '禁用' : '启用'}`);
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
      toast.success('实例已添加');
    } catch (err: unknown) {
      setRsshubError(err instanceof Error ? err.message : '添加失败');
      setRsshubInstances((prev) => prev.filter((i) => i.url !== url));
    } finally {
      setRsshubSaving(false);
    }
  };

  // ─── Delete instance（破坏性动作：二次确认） ───
  const deleteInstance = (url: string) => {
    setConfirmState({
      title: '删除 RSSHub 实例',
      message: (
        <>
          确定删除实例 <span className="break-all font-mono text-[12px] text-ink-900">{url}</span> 吗？
          使用该实例路由的信源会在下次同步时自动切换到其它可用实例。
        </>
      ),
      confirmLabel: '删除实例',
      onConfirm: async () => {
        const prev = rsshubInstances;
        setRsshubInstances((current) => current.filter((i) => i.url !== url));
        try {
          setRsshubSaving(true);
          await settingsApi.updateRSSHubInstances(rsshubInstances.filter((i) => i.url !== url));
          toast.success('实例已删除');
        } catch (err: unknown) {
          setRsshubError(err instanceof Error ? err.message : '删除失败');
          setRsshubInstances(prev);
        } finally {
          setRsshubSaving(false);
        }
      },
    });
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
      toast.success('信源已添加');
      await fetchSources(page);
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
      toast.success(result.message);
      void fetchSources(page);
      void fetchSourceMap();
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
      toast.success(result.message);
      setShowBatchImport(false);
      setBatchImportContent('');
      setBatchImportPreview([]);
      await fetchSources(page);
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
      toast.success('信源已更新');
      await fetchSources(page);
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

  const openAddModal = () => {
    setForm(emptyForm);
    setShowAddModal(true);
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
      await fetchSources(page);
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

  // 状态筛选（按 source.status + enabled 状态过滤）— 声明在前，供 filteredSourceMap 使用
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'syncing' | 'error' | 'disabled'>('all');
  // 批量选择：多选 + 批量启用/暂停
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchProcessing, setBatchProcessing] = useState(false);
  // 批量操作结果反馈（部分失败必须持久可见——见 handleBatchToggle）。
  const [batchResult, setBatchResult] = useState<{ tone: 'teal' | 'red'; text: string } | null>(null);

  const handleBatchToggle = async (enabled: boolean) => {
    if (selectedIds.size === 0 || batchProcessing) return;
    setBatchProcessing(true);
    setBatchResult(null);
    const ids = Array.from(selectedIds);
    try {
      // 逐条执行与失败收集见 _batch-utils.ts（纯函数，有单测覆盖）。
      // 单条失败不中断整批，但必须被收集并上抛到 UI。
      const failedIds = await runBatchToggle(
        ids,
        (id) => sourcesApi.update(id, { enabled }),
        (id, err) => console.error(`Batch toggle source ${id} failed:`, err),
      );
      // 执行完成后重建选择态：失败项保持选中以便直接重试。
      setSelectedIds((prev) => recomputeSelectionAfterBatch(prev, ids, failedIds));
      await fetchSources(page);
      await fetchSourceMap();

      const result = describeBatchResult(ids.length, failedIds, enabled);
      if (failedIds.length > 0) {
        // 部分失败：失败项保持选中可重试，需要持久可见 → 横幅（Toast 转瞬即逝不够）
        setBatchResult(result);
      } else {
        toast.success(result.text);
      }
    } finally {
      setBatchProcessing(false);
    }
  };

  // 批量暂停属禁用类破坏性动作，先过二次确认；批量启用不拦截
  const requestBatchPause = () => {
    if (selectedIds.size === 0 || batchProcessing) return;
    setConfirmState({
      title: '批量暂停信源',
      message: (
        <>
          将暂停 <b className="font-mono">{selectedIds.size}</b> 个已选信源的抓取，暂停期间不采集新内容，
          可随时重新勾选启用。
        </>
      ),
      confirmLabel: '批量暂停',
      onConfirm: () => handleBatchToggle(false),
    });
  };

  const runToggleEnabled = async (source: BackendSource) => {
    if (togglingIds.has(source.id)) return;
    const nextEnabled = !source.enabled;
    try {
      setTogglingIds((prev) => new Set(prev).add(source.id));
      await sourcesApi.update(source.id, { enabled: nextEnabled });
      await fetchSources(page);
      await fetchSourceMap();
      toast.success(nextEnabled ? `已启用「${source.name}」` : `已暂停「${source.name}」`);
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

  // 暂停属禁用类破坏性动作，二次确认后才执行；启用不拦截
  const handleToggleEnabled = (source: BackendSource) => {
    if (!source.enabled) {
      void runToggleEnabled(source);
      return;
    }
    setConfirmState({
      title: '暂停信源抓取',
      message: (
        <>
          暂停「<b>{source.name}</b>」后将停止采集新内容，可随时在行尾菜单中重新启用。
        </>
      ),
      confirmLabel: '暂停抓取',
      onConfirm: () => runToggleEnabled(source),
    });
  };

  // ─── Delete source（破坏性动作：二次确认） ───
  const handleDelete = (source: BackendSource) => {
    setConfirmState({
      title: '删除信源',
      message: (
        <>
          确定删除信源「<b>{source.name}</b>」吗？删除后停止抓取且不可恢复，已入库内容不受影响。
        </>
      ),
      confirmLabel: '删除',
      onConfirm: async () => {
        try {
          setDeletingIds((prev) => new Set(prev).add(source.id));
          await sourcesApi.delete(source.id);
          setSources((prev) => prev.filter((s) => s.id !== source.id));
          setMapSources((prev) => prev.filter((s) => s.id !== source.id));
          toast.success(`已删除「${source.name}」`);
        } catch (err: unknown) {
          setError(err instanceof Error ? err.message : '删除失败');
        } finally {
          setDeletingIds((prev) => {
            const next = new Set(prev);
            next.delete(source.id);
            return next;
          });
        }
      },
    });
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

  const syncBoard = useMemo(() => buildSourceSyncBoard(mapSources, syncingIds, new Date()), [mapSources, syncingIds]);

  // ─── 筛选与 chips ───

  const hasActiveFilters = searchKeyword.trim() !== '' || filterType !== '' || filterEnabled !== undefined;

  const handleSearchChange = (value: string) => {
    setSearchKeyword(value);
    setPage(1);
  };

  const handleTypeChange = (value: string) => {
    setFilterType(value);
    setPage(1);
  };

  const handleEnabledChange = (value: string) => {
    setFilterEnabled(value === '' ? undefined : value === 'yes');
    setPage(1);
  };

  const clearAllFilters = () => {
    setSearchResetKey((current) => current + 1);
    setSearchKeyword('');
    setFilterType('');
    setFilterEnabled(undefined);
    setPage(1);
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setPage(1);
  };

  const filterChips: AdminFilterChip[] = [];
  if (searchKeyword.trim()) {
    const keyword = searchKeyword.trim();
    filterChips.push({
      key: 'q',
      label: `搜索：${keyword.length > 16 ? `${keyword.slice(0, 16)}…` : keyword}`,
      onRemove: () => handleSearchChange(''),
    });
  }
  if (filterType) {
    filterChips.push({
      key: 'type',
      label: `类型：${filterType}`,
      onRemove: () => handleTypeChange(''),
    });
  }
  if (filterEnabled !== undefined) {
    filterChips.push({
      key: 'enabled',
      label: `状态：${filterEnabled ? '已启用' : '已禁用'}`,
      onRemove: () => handleEnabledChange(''),
    });
  }

  // ─── 列定义（操作列右侧粘性；高频动作同步/编辑直接可见，其余收「···」菜单） ───

  const columns: AdminTableColumn<BackendSource>[] = [
    {
      key: 'name',
      header: '名称',
      render: (source) => {
        const displayUrl = source.url ? redactSourceUrlForDisplay(source.url) : '';
        return (
          <div className="min-w-0">
            <span className="block max-w-[280px] truncate text-[13px] font-bold text-ink-900" title={source.name}>
              {source.name}
            </span>
            {displayUrl && (
              <span className="mt-0.5 block max-w-[280px] truncate text-[11px] text-ink-500" title={displayUrl}>
                {displayUrl}
              </span>
            )}
          </div>
        );
      },
    },
    {
      key: 'type',
      header: '类型',
      width: 92,
      render: (source) => (
        <Badge tone={TYPE_BADGE_TONE[source.source_type] ?? 'neutral'}>{source.source_type}</Badge>
      ),
    },
    {
      key: 'category',
      header: '分类',
      width: 110,
      render: (source) => <span className="truncate text-[13px] text-ink-700">{source.category || '未分类'}</span>,
    },
    {
      key: 'lastSync',
      header: '最后同步',
      width: 168,
      render: (source) => {
        const sourceSyncing = syncingIds.has(source.id) || source.status === 'syncing';
        return (
          <div className="min-w-0">
            <span className={cx('text-xs', source.sync_error ? 'text-red' : 'text-ink-500')}>
              {sourceSyncing ? '同步中' : source.sync_error ? '同步失败' : timeAgo(source.last_sync_at)}
            </span>
            {source.sync_error && (
              <span className="mt-0.5 block max-w-[210px] truncate text-[11px] text-red" title={source.sync_error}>
                {source.sync_error}
              </span>
            )}
            {syncResults[source.id] && (
              <span className="mt-0.5 block max-w-[210px] truncate text-[11px] text-teal" title={syncResults[source.id]}>
                {syncResults[source.id]}
              </span>
            )}
          </div>
        );
      },
    },
    {
      key: 'interval',
      header: '采集频率',
      width: 104,
      render: (source) => (
        <select
          value={source.fetch_interval_minutes}
          onChange={(e) => void handleIntervalChange(source.id, Number(e.target.value))}
          aria-label={`修改「${source.name}」的采集频率`}
          className="h-7 cursor-pointer rounded-xs border border-ink-200 bg-white px-1.5 text-xs text-ink-700 focus:border-admin-accent focus:outline-none"
        >
          {/* 当前值不在档位内时补一项，避免原生 select 显示空白 */}
          {!INTERVAL_OPTIONS.some((opt) => opt.value === source.fetch_interval_minutes) && (
            <option value={source.fetch_interval_minutes}>{source.fetch_interval_minutes}分钟</option>
          )}
          {INTERVAL_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      ),
    },
    {
      key: 'weight',
      header: '权重',
      width: 128,
      render: (source) => (
        <div
          className="flex items-center gap-0.5"
          title={`权重 ${source.weight}/5 — 影响精选加分：${source.weight > 3 ? '+' : ''}${(source.weight - 3) * 8} 分`}
        >
          {[1, 2, 3, 4, 5].map((w) => (
            <button
              key={w}
              type="button"
              aria-label={`将「${source.name}」权重设为 ${w}`}
              onClick={() => void handleWeightChange(source.id, w)}
              className={cx(
                'px-0.5 text-[11px] leading-none transition',
                w <= source.weight ? 'text-primary' : 'text-ink-200 hover:text-primary/50',
              )}
            >
              ●
            </button>
          ))}
          <span className="ml-1 text-[10px] text-ink-500">
            {(source.weight - 3) * 8 > 0 ? '+' : ''}{(source.weight - 3) * 8}
          </span>
        </div>
      ),
    },
    {
      key: 'status',
      header: '状态',
      width: 96,
      render: (source) => {
        const isActive = source.status === 'active' && source.enabled;
        return (
          <span className="flex items-center gap-1.5 text-[11px]">
            <span className={cx('h-2 w-2 rounded-full', isActive ? 'bg-teal' : 'bg-red')} aria-hidden="true" />
            <span className={isActive ? 'text-teal' : 'text-red'}>
              {source.enabled ? (source.status === 'active' ? '正常' : source.status) : '已禁用'}
            </span>
          </span>
        );
      },
    },
    {
      key: 'actions',
      header: '操作',
      width: 170,
      sticky: 'right',
      render: (source) => {
        const sourceSyncing = syncingIds.has(source.id) || source.status === 'syncing';
        const sourceDisabled = !source.enabled || source.status === 'disabled';
        const favoriteKey = getFavoriteTargetKey({ target_type: 'source', target_id: source.id });
        const isFavorite = favoriteTargets.has(favoriteKey) || sourceFavoriteKeys.has(favoriteKey);
        return (
          <div className="flex items-center justify-end gap-1.5">
            {/* 高频动作 ≤2 直接可见：同步 / 编辑 */}
            <Button
              type="button"
              onClick={() => void handleSync(source.id)}
              disabled={sourceSyncing || sourceDisabled}
              variant={sourceSyncing ? 'secondary' : 'success'}
              className="min-h-7 px-2.5 py-1 text-[11px]"
              title={sourceDisabled ? '信源已禁用，启用后可同步' : '同步信源'}
            >
              {sourceSyncing ? <Spinner /> : null}
              {sourceSyncing ? '同步中' : '同步'}
            </Button>
            <Button
              type="button"
              onClick={() => openEditModal(source)}
              variant="secondary"
              className="min-h-7 px-2.5 py-1 text-[11px]"
            >
              编辑
            </Button>
            {/* 其余动作收进行尾「···」菜单；暂停/删除在菜单内二次确认 */}
            <RowActionsMenu
              label={`「${source.name}」的更多操作`}
              items={[
                {
                  key: 'profile',
                  label: '证据画像',
                  icon: ShieldCheck,
                  onSelect: () => setEvidenceProfileSource(source),
                },
                {
                  key: 'favorite',
                  label: isFavorite ? '移出收藏' : '收藏信源',
                  icon: Star,
                  disabled: favoriteTargetPendingKeys.has(favoriteKey),
                  onSelect: () => void handleToggleSourceFavorite(source),
                },
                {
                  key: 'toggle',
                  label: source.enabled ? '暂停抓取' : '启用抓取',
                  icon: source.enabled ? Pause : Play,
                  disabled: togglingIds.has(source.id),
                  onSelect: () => handleToggleEnabled(source),
                },
                {
                  key: 'delete',
                  label: '删除信源',
                  icon: Trash2,
                  danger: true,
                  disabled: deletingIds.has(source.id),
                  onSelect: () => handleDelete(source),
                },
              ]}
            />
          </div>
        );
      },
    },
  ];

  const batchBar = (
    <div className="flex flex-wrap items-center gap-2 rounded-sm border border-primary-border bg-primary-light px-3 py-2 text-[13px]">
      已选 <b className="font-mono text-primary">{selectedIds.size}</b> 个信源
      <button
        type="button"
        onClick={() => setSelectedIds(new Set())}
        className="text-xs text-ink-500 underline-offset-2 transition hover:text-ink-900 hover:underline"
      >
        清除选择
      </button>
      <span className="mx-1 h-4 w-px bg-primary-border" aria-hidden="true" />
      <Button
        type="button"
        variant="success"
        onClick={() => void handleBatchToggle(true)}
        disabled={batchProcessing}
        className="min-h-7 px-2.5 py-1 text-[12px]"
      >
        {batchProcessing ? '处理中…' : '批量启用'}
      </Button>
      <Button
        type="button"
        variant="danger"
        onClick={requestBatchPause}
        disabled={batchProcessing}
        className="min-h-7 px-2.5 py-1 text-[12px]"
      >
        {batchProcessing ? '处理中…' : '批量暂停'}
      </Button>
    </div>
  );

  return (
    <AdminPageShell maxWidth={1200}>
      {/* Header */}
      <AdminPageHeader
        title="信源管理"
        description={<>共 <b className="font-mono text-ink-900">{total}</b> 个信源 · 活跃 <b className="font-mono text-ink-900">{activeCount}</b> 个</>}
        actions={
          <>
            <Button type="button" variant="primary" onClick={openAddModal} className="whitespace-nowrap">
              <Plus size={15} strokeWidth={2.2} />
              添加信源
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => opmlInputRef.current?.click()}
              disabled={importingOPML}
              className="whitespace-nowrap"
            >
              <Upload size={15} strokeWidth={2} />
              {importingOPML ? '导入中…' : '导入 OPML'}
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
          </>
        }
      />
      <input ref={opmlInputRef} aria-label="导入 OPML 文件" type="file" accept=".opml,.xml" className="hidden" onChange={handleOPMLImport} />
      <input ref={batchImportInputRef} aria-label="批量导入信源文件" type="file" accept=".json,.md,.txt,.opml,.xml" className="hidden" onChange={handleBatchImportFile} />

      {/* 筛选行：搜索（300ms 防抖内建）+ 类型/状态下拉；已选条件 chips 单移除 / 清空全部 */}
      <div className="space-y-2">
        <AdminFilters
          searchPlaceholder="搜索名称 / URL / 平台 / 分类…"
          searchValue={searchKeyword}
          resetKey={searchResetKey}
          onSearchChange={handleSearchChange}
        >
          <select
            value={filterType}
            onChange={(e) => handleTypeChange(e.target.value)}
            aria-label="按类型筛选"
            className="h-9 cursor-pointer rounded-xs border border-ink-200 bg-white px-2 text-[13px] text-ink-900 focus:border-admin-accent focus:outline-none"
          >
            <option value="">全部类型</option>
            {SOURCE_TYPE_FILTERS.map((type) => (
              <option key={type} value={type}>{type}</option>
            ))}
          </select>
          <select
            value={filterEnabled === undefined ? '' : filterEnabled ? 'yes' : 'no'}
            onChange={(e) => handleEnabledChange(e.target.value)}
            aria-label="按启用状态筛选"
            className="h-9 cursor-pointer rounded-xs border border-ink-200 bg-white px-2 text-[13px] text-ink-900 focus:border-admin-accent focus:outline-none"
          >
            <option value="">全部状态</option>
            <option value="yes">已启用</option>
            <option value="no">已禁用</option>
          </select>
        </AdminFilters>
        <AdminFilterChips chips={filterChips} onClearAll={clearAllFilters} />
      </div>

      <div className="mb-1 flex flex-wrap items-center justify-between gap-2.5">
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
                aria-pressed={active}
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

      {/* Error Banner（系统级 / 变更类错误；列表加载失败走 AdminTable 内联错误） */}
      {rsshubError && (
        <AdminNoticeBanner tone="red" onClose={() => setRsshubError(null)}>{rsshubError}</AdminNoticeBanner>
      )}

      {error && (
        <AdminNoticeBanner tone="red" onClose={() => setError(null)}>{error}</AdminNoticeBanner>
      )}

      {batchResult && (
        <AdminNoticeBanner tone={batchResult.tone} onClose={() => setBatchResult(null)}>{batchResult.text}</AdminNoticeBanner>
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
                ? 'border-primary-solid bg-primary-solid text-white'
                : 'border-gray-200 bg-white text-gray-700 hover:border-primary-border',
            )}
          >
            {tab.label}
            <span className={cx(
              'rounded-full px-1.5 text-[10px]',
              statusFilter === tab.value
                ? 'bg-white/20'
                // 异常计数跳出：错误数 > 0 时红色加粗（#121 统计条口径）
                : tab.value === 'error' && tab.count > 0
                  ? 'bg-red-light font-bold text-red-600'
                  : 'bg-gray-100',
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
          onEvidenceProfile={setEvidenceProfileSource}
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
          {currentUser?.role === 'admin' && <FeatureFlagsPanel onUpdate={updateEnabledFeatures} />}

          {/* 信源列表：三态（骨架 / 内联错误+重试 / 空态）由 AdminTable 内建，操作列右侧粘性 */}
          <div className="space-y-2">
            <PanelTitle icon={List} title="信源列表" hint="勾选行可批量启用 / 暂停" />
            <AdminTable
              columns={columns}
              rows={sources}
              rowKey={(source) => source.id}
              loading={loading}
              error={listError}
              onRetry={() => void fetchSources(page)}
              empty={
                <AdminEmptyState
                  compact
                  icon={FileSearch}
                  title={hasActiveFilters ? '没有匹配的信源' : '暂无信源'}
                  description={hasActiveFilters ? '试试更换关键词或放宽类型 / 状态筛选' : '添加第一个信源，开始采集内容'}
                  action={
                    hasActiveFilters ? (
                      <Button type="button" variant="secondary" onClick={clearAllFilters}>
                        清空筛选
                      </Button>
                    ) : (
                      <Button type="button" variant="primary" onClick={openAddModal}>
                        添加信源
                      </Button>
                    )
                  }
                />
              }
              selectable
              selected={selectedIds}
              onSelectedChange={(next) => setSelectedIds(new Set(Array.from(next, Number)))}
              batchBar={batchBar}
              minWidth={1040}
            />
          </div>

          {/* 分页：/sources 支持 page_size（1–200），每页条数选择器随之落地 */}
          {!loading && total > 0 && (
            <Pagination
              page={page}
              totalPages={totalPages}
              onPage={(next) => void fetchSources(typeof next === 'function' ? next(page) : next)}
              pageSize={pageSize}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              onPageSizeChange={handlePageSizeChange}
              summary={
                <>
                  第 <b className="font-mono">{(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)}</b> 条，共 {total} 条
                </>
              }
            />
          )}
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
      {evidenceProfileSource && (
        <EvidenceProfileModal source={evidenceProfileSource} onClose={() => setEvidenceProfileSource(null)} />
      )}

      {/* 破坏性动作二次确认（删除 / 暂停类统一入口，替代原生 confirm） */}
      {confirmState && (
        <AdminModal title={confirmState.title} onClose={() => { if (!confirmBusy) setConfirmState(null); }}>
          <p className="text-[13px] leading-6 text-ink-700">{confirmState.message}</p>
          <AdminModalFooter>
            <Button type="button" variant="secondary" onClick={() => setConfirmState(null)} disabled={confirmBusy} className="px-5">
              取消
            </Button>
            <Button type="button" variant="danger" onClick={() => void runConfirm()} disabled={confirmBusy} className="px-5">
              {confirmBusy ? '处理中…' : confirmState.confirmLabel}
            </Button>
          </AdminModalFooter>
        </AdminModal>
      )}
    </AdminPageShell>
  );
}
