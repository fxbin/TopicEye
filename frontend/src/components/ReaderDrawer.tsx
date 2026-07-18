'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, ExternalLink, FileWarning, RefreshCw, X } from 'lucide-react';
import { contentsApi } from '@/lib/api';
import type { ArticleReaderBlock, ArticleReaderSnapshot, ContentItem } from '@/types';
import { timeAgo } from '@/lib/datetime';
import { cx } from '@/components/ui';

// ─── 正文渲染（从 reader/page.tsx 抽出，保持一致）──

function legacyBlocks(text: string): ArticleReaderBlock[] {
  const paragraphGroups = text
    .split(/\n\s*\n+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const parts = paragraphGroups.length > 1
    ? paragraphGroups
    : text.split('\n').map((part) => part.trim()).filter(Boolean);
  return parts.map((value) => ({ type: 'paragraph', text: value }));
}

function ReaderBody({ blocks }: { blocks: ArticleReaderBlock[] }) {
  const rendered: React.ReactNode[] = [];
  let pendingList: string[] = [];

  const flushList = (key: string) => {
    if (pendingList.length === 0) return;
    rendered.push(
      <ul key={key} className="mb-8 list-disc space-y-2.5 pl-6 marker:text-primary">
        {pendingList.map((item, index) => <li key={index} className="pl-1 leading-[1.9]">{item}</li>)}
      </ul>,
    );
    pendingList = [];
  };

  blocks.forEach((block, index) => {
    if (block.type === 'list_item') {
      pendingList.push(block.text);
      return;
    }
    flushList(`list-${index}`);
    if (block.type === 'heading') {
      const isPrimary = (block.level || 2) <= 2;
      rendered.push(
        isPrimary
          ? <h2 key={index} className="mb-5 mt-12 text-[24px] font-black leading-[1.45] text-[#24221f] first:mt-1 sm:text-[27px]">{block.text}</h2>
          : <h3 key={index} className="mb-4 mt-10 text-[19px] font-extrabold leading-[1.55] text-[#2d2a26] sm:text-[21px]">{block.text}</h3>,
      );
      return;
    }
    if (block.type === 'quote') {
      rendered.push(
        <blockquote key={index} className="my-9 border-l-[3px] border-primary bg-[#fff7ef] px-5 py-4 text-[16px] leading-8 text-[#625c54] sm:text-[17px]">
          {block.text}
        </blockquote>,
      );
      return;
    }
    if (block.type === 'code') {
      rendered.push(
        <pre key={index} className="my-7 overflow-x-auto rounded-lg border border-gray-200 bg-[#1e1e2e] p-4 text-[13px] leading-relaxed text-[#cdd6f4]">
          <code className="font-mono whitespace-pre">{block.text}</code>
        </pre>,
      );
      return;
    }
    rendered.push(<p key={index} className="mb-7 last:mb-0">{block.text}</p>);
  });
  flushList('list-final');
  return <>{rendered}</>;
}

// ─── 抽屉组件 ──

export interface ReaderDrawerProps {
  /** 要阅读的内容 ID；null 时关闭抽屉 */
  contentId: number | null;
  onClose: () => void;
}

export function ReaderDrawer({ contentId, onClose }: ReaderDrawerProps) {
  const [content, setContent] = useState<ContentItem | null>(null);
  const [snapshot, setSnapshot] = useState<ArticleReaderSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (id: number, refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const item = await contentsApi.get(id);
      setContent(item);
      const reader = await contentsApi.reader(id, refresh);
      setSnapshot(reader);
    } catch (err) {
      setError(err instanceof Error ? err.message : '暂时无法提取原文');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (contentId !== null && contentId > 0) {
      setContent(null);
      setSnapshot(null);
      void load(contentId);
    }
  }, [contentId, load]);

  // ESC 关闭
  useEffect(() => {
    if (contentId === null) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [contentId, onClose]);

  const body = useMemo(
    () => snapshot?.content_blocks?.length ? snapshot.content_blocks : legacyBlocks(snapshot?.text_content || ''),
    [snapshot],
  );
  const sourceUrl = content?.url || snapshot?.canonical_url;
  const isOpen = contentId !== null;

  return (
    <>
      {/* 遮罩 */}
      <div
        className={cx(
          'fixed inset-0 z-40 bg-black/40 transition-opacity duration-300',
          isOpen ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={onClose}
      />

      {/* 抽屉面板 */}
      <div
        className={cx(
          'fixed right-0 top-0 z-50 flex h-full w-full max-w-[680px] flex-col bg-[#F7F8FA] shadow-2xl transition-transform duration-300',
          isOpen ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        {/* 顶部栏 */}
        <div className="flex shrink-0 items-center justify-between border-b border-[#e9e4dc] bg-[#fffefd] px-5 py-3">
          <span className="flex items-center gap-1.5 text-xs font-bold text-gray-500">
            <BookOpen size={14} className="text-primary" /> 站内阅读
          </span>
          <div className="flex items-center gap-3">
            {sourceUrl && (
              <a
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-bold text-teal no-underline hover:text-primary"
              >
                打开原文 <ExternalLink size={12} />
              </a>
            )}
            <button
              type="button"
              onClick={onClose}
              className="grid h-7 w-7 place-items-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              title="关闭 (Esc)"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* 内容区 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-8 sm:py-6">
          <div className="mx-auto max-w-[640px]">
            {loading && (
              <div className="space-y-4">
                <div className="h-4 w-24 animate-pulse rounded bg-[#f0ece7]" />
                <div className="h-9 w-4/5 animate-pulse rounded bg-[#f0ece7]" />
                <div className="h-4 w-2/5 animate-pulse rounded bg-[#f4f1ed]" />
                <div className="mt-10 space-y-5">
                  {[1, 2, 3, 4, 5].map((i) => <div key={i} className="h-4 animate-pulse rounded bg-[#f5f2ee]" />)}
                </div>
              </div>
            )}

            {!loading && error && (
              <div className="rounded-lg border border-amber-border bg-amber-light/40 p-6 text-center">
                <FileWarning size={28} className="mx-auto mb-3 text-amber" />
                <h2 className="mb-2 text-base font-black text-gray-900">暂时无法站内阅读</h2>
                <p className="mx-auto mb-4 max-w-md text-sm leading-6 text-gray-600">{error}</p>
                <div className="flex flex-wrap justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => contentId && void load(contentId, true)}
                    disabled={refreshing}
                    className="inline-flex items-center gap-1 rounded border border-gray-200 bg-white px-3 py-1.5 text-xs font-bold text-gray-600 hover:text-primary"
                  >
                    <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} /> 重试
                  </button>
                  {sourceUrl && (
                    <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded border border-teal-border bg-white px-3 py-1.5 text-xs font-bold text-teal no-underline">
                      打开原文 <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              </div>
            )}

            {!loading && snapshot && (
              <article>
                <header className="mb-7">
                  <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-gray-400">
                    {content?.source_name && <span className="font-semibold text-gray-500">{content.source_name}</span>}
                    <span>·</span>
                    <span>约 {snapshot.reading_minutes} 分钟</span>
                  </div>
                  <h1 className="mb-3 text-[26px] font-black leading-[1.35] tracking-[-0.02em] text-[#1f1d1a] sm:text-[32px]">{snapshot.title}</h1>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-400">
                    {snapshot.byline && <span>{snapshot.byline}</span>}
                    {snapshot.published_at && <span>· {new Date(snapshot.published_at).toLocaleDateString('zh-CN')}</span>}
                    <span>· 提取于 {timeAgo(snapshot.fetched_at)}</span>
                  </div>
                  {snapshot.excerpt && (
                    <p className="mt-5 border-l-[3px] border-primary pl-4 text-[14px] leading-7 text-[#6d665e] sm:text-[15px]">{snapshot.excerpt}</p>
                  )}
                </header>

                <section className="border-t border-[#ece7e0] pt-7">
                  <div className="reader-content font-serif text-[16px] leading-[1.95] text-[#302d29] sm:text-[17px]">
                    <ReaderBody blocks={body} />
                  </div>
                </section>

                <div className="mt-8 flex items-center justify-between border-t border-[#ece7e0] pt-5 text-xs">
                  <button
                    type="button"
                    onClick={() => contentId && void load(contentId, true)}
                    disabled={refreshing}
                    className="inline-flex items-center gap-1 font-bold text-primary disabled:opacity-50"
                  >
                    <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} /> 更新快照
                  </button>
                  {sourceUrl && (
                    <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-bold text-teal no-underline">
                      查看来源 <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              </article>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
