/**
 * 微信读书书架页卡片组件。
 *
 * 从 _shared.tsx 拆出：BookCard, DiscoverBookCard, BookDetailPanel, StatCard
 */

'use client';

import React from 'react';
import {
  BookOpen,
  ExternalLink,
  Highlighter,
  MessageSquare,
  X,
  Star,
  Clock,
} from 'lucide-react';
import { useDialogFocus } from '@/components/useDialogFocus';
import { Panel, Badge, cx } from '@/components/ui';
import { AutoLink } from '@/components/AutoLink';
import type {
  ContentItem,
  WeReadSearchBook,
} from '@/types';
import {
  type WeReadMeta,
  getReadingStatus,
  isPausedReading,
  wereadBookUrl,
  wereadSearchUrl,
  WEREAD_FALLBACK_URL,
} from './_weread-utils';
import { BestBookmarksSection } from './_weread-stats';

// ── 书架卡片 ──

export function BookCard({ item, meta, onExpand }: {
  item: ContentItem;
  meta: WeReadMeta;
  onExpand: () => void;
}) {
  const status = getReadingStatus(meta.readingProgress);
  const statusColor = status === '已读' ? 'teal' : status === '在读' ? 'primary' : 'neutral';
  const paused = isPausedReading(meta, item.published_at || null);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onExpand}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onExpand(); }}
      className="group relative flex cursor-pointer flex-col items-center text-center transition hover:-translate-y-1"
    >
      {/* 封面 */}
      <div className="relative mb-2 h-[140px] w-[100px] shrink-0">
        {item.cover_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.cover_url}
            alt=""
            className="h-full w-full rounded-md object-cover shadow-sm transition group-hover:shadow-lg"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
              const sib = (e.target as HTMLImageElement).nextElementSibling as HTMLElement | null;
              if (sib) sib.style.display = 'flex';
            }}
          />
        ) : null}
        <div
          className={cx(
            'absolute inset-0 grid place-items-center rounded-md bg-gray-100 shadow-sm',
            item.cover_url ? 'hidden' : 'flex',
          )}
        >
          <BookOpen size={20} className="text-gray-300" />
        </div>

        {/* 进度条叠加在封面底部 */}
        {meta.readingProgress > 0 && (
          <div className="absolute bottom-0 left-0 right-0 overflow-hidden rounded-b-md bg-black/50 backdrop-blur-sm">
            <div
              className={cx(
                'h-1',
                status === '已读' ? 'bg-teal' : 'bg-primary',
              )}
              style={{ width: `${meta.readingProgress}%` }}
            />
          </div>
        )}

        {/* 跳转微信读书按钮 — 悬停显示 */}
        <a
          href={wereadBookUrl(item)}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          title="在微信读书中打开"
          className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-white/90 opacity-0 shadow-md transition group-hover:opacity-100 hover:bg-white hover:text-primary"
        >
          <ExternalLink size={11} />
        </a>
      </div>

      {/* 书名 */}
      <h3 className="line-clamp-2 max-w-[110px] text-xs font-bold leading-4 text-gray-800">
        {item.title}
      </h3>

      {/* 作者 */}
      {item.author && (
        <p className="mt-0.5 line-clamp-1 max-w-[110px] text-[10px] text-gray-400">
          {item.author}
        </p>
      )}

      {/* 划线/想法徽章 */}
      <div className="mt-1 flex items-center gap-1">
        {meta.noteCount > 0 && (
          <span className="inline-flex items-center gap-0.5 rounded-full bg-primary-light px-1.5 py-0.5 text-[9px] font-bold text-primary">
            <Highlighter size={8} />
            {meta.noteCount}
          </span>
        )}
        {meta.reviewCount > 0 && (
          <span className="inline-flex items-center gap-0.5 rounded-full bg-teal-light px-1.5 py-0.5 text-[9px] font-bold text-teal">
            <MessageSquare size={8} />
            {meta.reviewCount}
          </span>
        )}
        {meta.noteCount === 0 && meta.reviewCount === 0 && (
          <span className="text-[9px] text-gray-300">无笔记</span>
        )}
      </div>

      {/* 状态标签 */}
      <span
        className={cx(
          'mt-1 rounded-full px-1.5 py-0.5 text-[9px] font-bold',
          statusColor === 'teal' && 'bg-teal-light text-teal',
          statusColor === 'primary' && 'bg-primary-light text-primary',
          statusColor === 'neutral' && 'bg-gray-100 text-gray-400',
        )}
      >
        {status}
      </span>
      {/* 暂停阅读标记 */}
      {paused && (
        <span className="mt-0.5 inline-flex items-center gap-0.5 rounded-full bg-amber-light px-1.5 py-0.5 text-[9px] font-bold text-amber">
          <Clock size={8} />
          暂停
        </span>
      )}
    </div>
  );
}

// ── 发现模式搜索结果卡片 ──

export function DiscoverBookCard({ book, inShelf }: {
  book: WeReadSearchBook;
  inShelf: boolean;
}) {
  const ratingLabel = book.newRatingDetail?.title;
  const ratingColor =
    ratingLabel === '神作' ? 'teal' :
    ratingLabel === '好评如潮' || ratingLabel === '值得一读' ? 'primary' :
    'neutral';

  return (
    <div className="group flex flex-col items-center text-center transition hover:-translate-y-1">
      {/* 封面 */}
      <div className="relative mb-2 h-[140px] w-[100px] shrink-0">
        {book.cover ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={book.cover}
            alt=""
            className="h-full w-full rounded-md object-cover shadow-sm transition group-hover:shadow-lg"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
              const sib = (e.target as HTMLImageElement).nextElementSibling as HTMLElement | null;
              if (sib) sib.style.display = 'flex';
            }}
          />
        ) : null}
        <div
          className={cx(
            'absolute inset-0 grid place-items-center rounded-md bg-gray-100 shadow-sm',
            book.cover ? 'hidden' : 'flex',
          )}
        >
          <BookOpen size={20} className="text-gray-300" />
        </div>

        {/* 已在书架角标 */}
        {inShelf && (
          <div className="absolute right-0 top-0 rounded-bl-md rounded-tr-md bg-teal px-1.5 py-0.5 text-[9px] font-black text-white shadow">
            书架中
          </div>
        )}
      </div>

      {/* 书名 */}
      <h3 className="line-clamp-2 max-w-[110px] text-xs font-bold leading-4 text-gray-800">
        {book.title}
      </h3>

      {/* 作者 */}
      {book.author && (
        <p className="mt-0.5 line-clamp-1 max-w-[110px] text-[10px] text-gray-400">
          {book.author}
        </p>
      )}

      {/* 评分徽章 */}
      <div className="mt-1 flex items-center gap-1">
        {book.newRating && (
          <span
            className={cx(
              'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-bold',
              ratingColor === 'teal' && 'bg-teal-light text-teal',
              ratingColor === 'primary' && 'bg-primary-light text-primary',
              ratingColor === 'neutral' && 'bg-gray-100 text-gray-400',
            )}
          >
            <Star size={8} className="fill-current" />
            {(book.newRating / 10).toFixed(1)}
          </span>
        )}
        {book.readingCount !== undefined && book.readingCount > 0 && (
          <span className="text-[9px] text-gray-400">
            {book.readingCount > 10000 ? `${(book.readingCount / 10000).toFixed(1)}万` : book.readingCount} 人在读
          </span>
        )}
      </div>

      {/* 外链 — 始终显示 */}
      <a
        href={book.deepLink || wereadSearchUrl(book.title)}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 inline-flex items-center gap-0.5 text-[9px] font-bold text-primary hover:underline"
        onClick={(e) => e.stopPropagation()}
      >
        去读
        <ExternalLink size={8} />
      </a>
    </div>
  );
}

// ── 划线详情面板 ──

export function BookDetailPanel({ item, meta, onClose }: {
  item: ContentItem;
  meta: WeReadMeta;
  onClose: () => void;
}) {
  const { dialogRef, onKeyDown } = useDialogFocus<HTMLDivElement>(true, onClose);
  const status = getReadingStatus(meta.readingProgress);
  return (
    <>
      <div aria-hidden="true" className="fixed inset-0 z-50 bg-black/40" onClick={onClose} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="weread-book-detail-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="pointer-events-none fixed inset-0 z-[51] flex items-center justify-center p-4"
      >
        <Panel className="pointer-events-auto max-h-[85vh] w-full max-w-2xl overflow-y-auto p-6">
        {/* 头部 */}
        <div className="mb-4 flex items-start gap-4">
          <div className="h-[120px] w-[90px] shrink-0">
            {item.cover_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={item.cover_url}
                alt=""
                className="h-full w-full rounded-md object-cover shadow-md"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
              />
            ) : (
              <div className="grid h-full w-full place-items-center rounded-md bg-gray-100">
                <BookOpen size={24} className="text-gray-300" />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="weread-book-detail-title" className="mb-1 break-words text-lg font-black text-gray-900">{item.title}</h2>
            {item.author && (
              <p className="mb-2 text-sm text-gray-500">{item.author}</p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {meta.noteCount > 0 && (
                <Badge tone="primary">
                  <Highlighter size={10} className="mr-1" />
                  {meta.noteCount} 条划线
                </Badge>
              )}
              {meta.reviewCount > 0 && (
                <Badge tone="teal">
                  <MessageSquare size={10} className="mr-1" />
                  {meta.reviewCount} 条想法
                </Badge>
              )}
              <Badge tone={status === '已读' ? 'teal' : status === '在读' ? 'primary' : 'neutral'}>
                阅读进度 {meta.readingProgress}% · {status}
              </Badge>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
            aria-label="关闭书籍详情"
          >
            <X size={18} />
          </button>
        </div>

        {/* 进度条 */}
        {meta.readingProgress > 0 && (
          <div className="mb-4">
            <div className="h-2 overflow-hidden rounded-full bg-gray-100">
              <div
                className={cx('h-full rounded-full', status === '已读' ? 'bg-teal' : 'bg-primary')}
                style={{ width: `${meta.readingProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* 划线/笔记内容 */}
        {item.summary && (
          <div className="mb-4">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-black text-gray-500">
              <Highlighter size={12} />
              笔记摘要
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50 p-4 text-[13px] leading-7 text-gray-700">
              <AutoLink text={item.summary} />
            </div>
          </div>
        )}

        {/* 热门划线 */}
        <BestBookmarksSection item={item} />

        {item.raw_content && item.raw_content !== item.summary && (
          <div className="mb-4">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-black text-gray-500">
              <BookOpen size={12} />
              原始划线内容
            </div>
            <div className="max-h-[300px] overflow-y-auto rounded-lg border border-gray-100 bg-white p-4 text-[13px] leading-7 text-gray-600">
              <AutoLink text={item.raw_content} />
            </div>
          </div>
        )}

        {/* 外链 — 始终显示，没有直接 URL 时用搜索 */}
        <a
          href={wereadBookUrl(item)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline"
        >
          在微信读书中{item.url && item.url !== WEREAD_FALLBACK_URL ? '查看' : '搜索'}
          <ExternalLink size={12} />
        </a>
        </Panel>
      </div>
    </>
  );
}

// ── 统计卡片 ──

export function StatCard({ icon: Icon, label, value, tone }: {
  icon: typeof BookOpen;
  label: string;
  value: string | number;
  tone: 'primary' | 'teal' | 'purple' | 'amber';
}) {
  const toneClass = {
    primary: 'bg-primary-light text-primary',
    teal: 'bg-teal-light text-teal',
    purple: 'bg-purple-light text-purple',
    amber: 'bg-amber-light text-amber',
  }[tone];
  return (
    <Panel className="flex items-center gap-3 p-3.5">
      <div className={cx('flex h-9 w-9 items-center justify-center rounded-sm', toneClass)}>
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[10px] font-bold text-gray-400">{label}</div>
        <div className="font-mono text-lg font-black text-gray-900">{value}</div>
      </div>
    </Panel>
  );
}
