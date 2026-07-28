'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, BookOpen, ExternalLink, FileWarning, RefreshCw } from 'lucide-react';
import { Button, Panel } from '@/components/ui';
import { contentsApi } from '@/lib/api';
import type { ArticleReaderBlock, ArticleReaderSnapshot, ContentItem } from '@/types';
import { timeAgo } from '@/lib/datetime';
import { AutoLink } from '@/components/AutoLink';
import EvidencePanel from '@/components/EvidencePanel';

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
      pendingList.push(block.text ?? '');
      return;
    }
    flushList(`list-${index}`);
    if (block.type === 'image') {
      if (!block.src) return;
      rendered.push(
        <figure key={index} className="my-8">
          <img
            src={block.src}
            alt={block.alt ?? ''}
            loading="lazy"
            referrerPolicy="no-referrer"
            onError={(e) => { const fig = e.currentTarget.parentElement; if (fig) fig.style.display = 'none'; }}
            className="mx-auto max-h-[72vh] w-auto max-w-full rounded-lg border border-[#ece7e0] bg-[#faf8f5]"
          />
          {block.alt && <figcaption className="mt-2.5 text-center text-[13px] leading-6 text-[#8a8279]">{block.alt}</figcaption>}
        </figure>,
      );
      return;
    }
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
          <AutoLink text={block.text ?? ''} />
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
    rendered.push(<p key={index} className="mb-7 last:mb-0"><AutoLink text={block.text} /></p>);
  });
  flushList('list-final');
  return <>{rendered}</>;
}

export default function ContentReaderPage() {
  const params = useParams();
  const router = useRouter();
  const contentId = Number(params.id);
  const [content, setContent] = useState<ContentItem | null>(null);
  const [snapshot, setSnapshot] = useState<ArticleReaderSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    if (!Number.isFinite(contentId) || contentId <= 0) {
      setError('内容编号无效');
      setLoading(false);
      return;
    }
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const item = await contentsApi.get(contentId);
      setContent(item);
      const reader = await contentsApi.reader(contentId, refresh);
      setSnapshot(reader);
    } catch (err) {
      setError(err instanceof Error ? err.message : '暂时无法提取原文');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [contentId]);

  useEffect(() => { void load(); }, [load]);

  const body = useMemo(
    () => snapshot?.content_blocks?.length ? snapshot.content_blocks : legacyBlocks(snapshot?.text_content || ''),
    [snapshot],
  );
  const sourceUrl = content?.url || snapshot?.canonical_url;

  return (
    <div className="fade-in min-h-full overflow-y-auto bg-[#F7F8FA] px-5 py-6 sm:px-10 sm:py-8">
      <main className="mx-auto max-w-[860px]">
        <div className="mb-5 flex items-center justify-between gap-3">
          <Button type="button" variant="ghost" onClick={() => router.back()} className="min-h-0 px-0 py-1 text-[13px]">
            <ArrowLeft size={15} /> 返回
          </Button>
          {sourceUrl && (
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs font-bold text-teal no-underline hover:text-primary">
              打开原文 <ExternalLink size={13} />
            </a>
          )}
        </div>

        {loading && (
          <div className="overflow-hidden rounded-[18px] border border-[#e9e4dc] bg-[#fffefd] shadow-[0_1px_2px_rgba(25,20,15,0.03)]">
            <div className="mx-auto max-w-[700px] px-7 py-10 sm:px-14 sm:py-14">
              <div className="mb-5 h-4 w-24 animate-pulse rounded bg-[#f0ece7]" />
              <div className="mb-3 h-10 w-4/5 animate-pulse rounded bg-[#f0ece7]" />
              <div className="h-4 w-2/5 animate-pulse rounded bg-[#f4f1ed]" />
              <div className="mt-12 space-y-5">
                {[1, 2, 3, 4].map((line) => <div key={line} className="h-4 animate-pulse rounded bg-[#f5f2ee]" />)}
              </div>
            </div>
          </div>
        )}

        {!loading && error && (
          <Panel className="border-amber-border bg-amber-light/40 p-7 text-center">
            <FileWarning size={30} className="mx-auto mb-3 text-amber" />
            <h1 className="mb-2 text-lg font-black text-gray-900">暂时无法站内阅读</h1>
            <p className="mx-auto mb-5 max-w-lg text-sm leading-7 text-gray-600">{error}</p>
            <div className="flex flex-wrap justify-center gap-2.5">
              <Button type="button" variant="secondary" onClick={() => void load(true)} disabled={refreshing}>
                <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} /> 重试
              </Button>
              {sourceUrl && (
                <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-xs border border-teal-border bg-white px-3 py-2 text-xs font-bold text-teal no-underline">
                  打开原文 <ExternalLink size={13} />
                </a>
              )}
            </div>
          </Panel>
        )}

        {!loading && snapshot && (
          <article>
            <div className="overflow-hidden rounded-[18px] border border-[#e9e4dc] bg-[#fffefd] shadow-[0_1px_2px_rgba(25,20,15,0.03)]">
              <header className="mx-auto max-w-[700px] px-7 pb-8 pt-10 sm:px-14 sm:pb-10 sm:pt-14">
                <div className="mb-5 flex flex-wrap items-center gap-2.5 text-xs">
                  <span className="rounded-full bg-primary-light px-2.5 py-1 font-bold text-primary">站内阅读</span>
                  {content?.source_name && <span className="font-semibold text-gray-500">{content.source_name}</span>}
                  <span className="text-gray-300">·</span>
                  <span className="text-gray-400">约 {snapshot.reading_minutes} 分钟</span>
                </div>
                <h1 className="mb-5 text-[29px] font-black leading-[1.32] tracking-[-0.02em] text-[#1f1d1a] sm:text-[38px]">{snapshot.title}</h1>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-400">
                  {snapshot.byline && <span>{snapshot.byline}</span>}
                  {snapshot.byline && snapshot.published_at && <span>·</span>}
                  {snapshot.published_at && <span>{new Date(snapshot.published_at).toLocaleDateString('zh-CN')}</span>}
                  <span>{snapshot.byline || snapshot.published_at ? '·' : ''} 提取于 {timeAgo(snapshot.fetched_at)}</span>
                </div>
                <div className="mt-6 flex flex-col gap-3 rounded-lg border border-amber-border bg-amber-light/35 px-4 py-3 text-xs sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-2 text-gray-600">
                    <FileWarning size={15} className="mt-0.5 shrink-0 text-amber" />
                    <div>
                      <span className="font-bold text-gray-700">文本快照</span>
                      <span className="ml-1.5 text-gray-500">这是清洗后的文本快照，来源页面可能已经更新。</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-3 pl-[23px] sm:pl-0">
                    <button type="button" onClick={() => void load(true)} disabled={refreshing} className="inline-flex items-center gap-1 border-0 bg-transparent p-0 text-xs font-bold text-primary disabled:opacity-50">
                      <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} /> 更新快照
                    </button>
                    {sourceUrl && <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-bold text-teal no-underline">查看来源 <ExternalLink size={13} /></a>}
                  </div>
                </div>
                {snapshot.excerpt && <p className="mt-7 border-l-[3px] border-primary pl-4 text-[15px] leading-7 text-[#6d665e] sm:text-[16px]">{snapshot.excerpt}</p>}
              </header>

              <section className="border-t border-[#ece7e0]">
                <div className="mx-auto max-w-[700px] px-7 py-9 sm:px-14 sm:py-12">
                  <div className="mb-8 flex items-center gap-2 text-xs font-bold tracking-[0.08em] text-[#82796f]">
                    <BookOpen size={15} className="text-primary" /> 原文快照
                  </div>
                  <div className="reader-content font-serif text-[17px] leading-[2] text-[#302d29] sm:text-[18px]">
                    <ReaderBody blocks={body} />
                  </div>
                </div>
              </section>
            </div>

            {/* Cross-source evidence panel */}
            {contentId > 0 && (
              <div className="mt-4">
                <EvidencePanel contentId={contentId} />
              </div>
            )}
          </article>
        )}
      </main>
    </div>
  );
}
