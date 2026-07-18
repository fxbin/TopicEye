'use client';

import React, { useState } from 'react';
import { BookOpen, ExternalLink, RefreshCw } from 'lucide-react';
import { contentsApi, integrationsApi } from '@/lib/api';
import { Panel, cx } from '@/components/ui';
import { Pagination } from '@/components/Pagination';
import { ErrorState, LoadingState } from '@/components/StateView';
import { useFetch } from '@/hooks/useFetch';
import type { ContentItem } from '@/types';
import { AutoLink } from '@/components/AutoLink';

const PAGE_SIZE = 30;

export default function WeReadPage() {
  const [page, setPage] = useState(1);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const { data, loading, error, refetch } = useFetch(
    () => contentsApi.list({ platform: '微信读书', page, page_size: PAGE_SIZE }),
    [page],
  );

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const result = await integrationsApi.syncWeRead(50);
      setSyncMsg(`同步完成：新 ${result.new} 条，重复 ${result.duplicates} 条，共获取 ${result.fetched} 条`);
      refetch();
    } catch (err) {
      setSyncMsg(err instanceof Error ? err.message : '同步失败，请先在个人中心配置微信读书 API Key');
    } finally {
      setSyncing(false);
    }
  };

  if (loading && items.length === 0) return <LoadingState />;
  if (error && items.length === 0) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <div className="h-full w-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 p-4">
        {/* 头部 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen size={20} className="text-primary" />
            <h1 className="text-lg font-black text-gray-900">微信读书素材</h1>
            {total > 0 && (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-bold text-gray-500">
                {total} 条
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className={cx(
              'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-bold transition',
              syncing
                ? 'border-gray-200 text-gray-300'
                : 'border-gray-200 text-gray-600 hover:text-primary hover:border-primary-border',
            )}
          >
            <RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />
            {syncing ? '同步中…' : '同步素材'}
          </button>
        </div>

        {/* 同步反馈 */}
        {syncMsg && (
          <div
            className={cx(
              'rounded-lg border px-3 py-2 text-xs',
              syncMsg.startsWith('同步完成')
                ? 'border-teal-border bg-teal-light text-teal'
                : 'border-red-light bg-red-light text-red',
            )}
          >
            {syncMsg}
          </div>
        )}

        {/* 空状态 */}
        {items.length === 0 && !loading && (
          <Panel className="p-8 text-center">
            <BookOpen size={32} className="mx-auto mb-3 text-gray-300" />
            <p className="text-sm font-bold text-gray-500">还没有微信读书素材</p>
            <p className="mt-1 text-xs text-gray-400">
              请先在
              <a href="/profile" className="mx-0.5 text-primary hover:underline">个人中心</a>
              配置微信读书 API Key，然后点击右上角「同步素材」。
            </p>
          </Panel>
        )}

        {/* 素材列表 */}
        <div className="space-y-2">
          {items.map((item) => (
            <Panel key={item.id} className="p-4 transition hover:shadow-md">
              <div className="flex items-start gap-3">
                {item.cover_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={item.cover_url}
                    alt=""
                    className="h-16 w-12 shrink-0 rounded object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                ) : (
                  <div className="grid h-16 w-12 shrink-0 place-items-center rounded bg-gray-100">
                    <BookOpen size={16} className="text-gray-300" />
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-start gap-2">
                    <h3 className="min-w-0 flex-1 break-words text-sm font-bold leading-6 text-gray-900">
                      {item.title}
                    </h3>
                    {item.url && item.url !== 'https://weread.qq.com/r/weread-skills' && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-0.5 shrink-0 text-gray-300 hover:text-primary"
                      >
                        <ExternalLink size={13} />
                      </a>
                    )}
                  </div>
                  {item.author && (
                    <div className="mt-0.5 text-[11px] text-gray-400">{item.author}</div>
                  )}
                  {item.summary && (
                    <div className="mt-1.5 text-[13px] leading-6 text-gray-600">
                      <AutoLink text={item.summary} />
                    </div>
                  )}
                  {Array.isArray(item.tags) && item.tags.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {item.tags.map((tag, i) => (
                        <span
                          key={`${tag}-${i}`}
                          className="rounded-full border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-400"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </Panel>
          ))}
        </div>

        {/* 分页 */}
        {totalPages > 1 && (
          <Pagination
            page={page}
            totalPages={totalPages}
            onPage={setPage}
            summary={<span className="text-xs font-bold text-gray-500">{page} / {totalPages}</span>}
          />
        )}
      </div>
    </div>
  );
}
