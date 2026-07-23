'use client';

import React from 'react';
import { BookOpen, ExternalLink, Star } from 'lucide-react';
import { Button, Panel, cx } from '@/components/ui';
import LevelBadge from '@/components/LevelBadge';
import { useAppContext } from '@/components/ClientLayout';
import type { ContentItem, ContentAnalysis, RecommendLevel } from '@/types';

interface TopicHeaderCardProps {
  item: ContentItem;
  analysis: ContentAnalysis | null;
  level: RecommendLevel;
  tags: string[];
  isFav: boolean;
  favoritePending?: boolean;
  onToggleFavorite: () => void;
  timeAgoStr: string;
}

export default function TopicHeaderCard({
  item,
  analysis: _analysis, // eslint-disable-line @typescript-eslint/no-unused-vars
  level,
  tags,
  isFav,
  favoritePending = false,
  onToggleFavorite,
  timeAgoStr,
}: TopicHeaderCardProps) {
  const { openReader } = useAppContext();
  return (
    <Panel className="mb-5 p-8">
      {/* Level + Tags */}
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <LevelBadge level={level} />
        {tags.map((c) => (
          <span key={c} className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
            {c}
          </span>
        ))}
      </div>

      {/* Title */}
      <h1 className="mb-3 text-2xl font-bold leading-normal text-gray-900">
        {item.title}
      </h1>

      {/* Meta */}
      <div className="flex flex-wrap items-center gap-4 text-[13px] text-gray-400">
        {item.source_name && (
          <span>
            <b className="text-gray-600">{item.source_name}</b>
          </span>
        )}
        {timeAgoStr && <span>{timeAgoStr}</span>}
        <span className="text-gray-300">|</span>
        {item.source_type && <span>{item.source_type}</span>}
        {item.author && (
          <>
            <span className="text-gray-300">|</span>
            <span>{item.author}</span>
          </>
        )}
      </div>

      {/* Action bar */}
      <div className="mt-5 flex flex-wrap gap-3">
        <Button
          type="button"
          variant={isFav ? 'primary' : 'secondary'}
          onClick={onToggleFavorite}
          disabled={favoritePending}
        >
          <Star size={14} strokeWidth={2} fill={isFav ? '#FFFFFF' : 'none'} />
          {favoritePending ? '处理中' : isFav ? '已收藏' : '收藏选题'}
        </Button>

        {item.url && (
          <button
            type="button"
            onClick={() => openReader(item.id)}
            className={cx('inline-flex min-h-9 items-center justify-center gap-1.5 rounded-sm border border-primary-border bg-primary-light px-3 py-2 text-xs font-bold text-primary transition')}
          >
            <BookOpen size={13} strokeWidth={2} />
            站内阅读
          </button>
        )}

        {item.url && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className={cx('inline-flex min-h-9 items-center justify-center gap-1.5 rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold text-teal no-underline transition')}
          >
            查看原文
            <ExternalLink size={13} strokeWidth={2} />
          </a>
        )}
      </div>
    </Panel>
  );
}
