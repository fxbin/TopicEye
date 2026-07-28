'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Star } from 'lucide-react';
import { cx, Panel } from '@/components/ui';
import type { Topic } from '@/types';
import LevelBadge from './LevelBadge';
import PlatformTag from './PlatformTag';
import ScoreBar from './ScoreBar';

interface TopicCardProps {
  topic: Topic;
  isFav: boolean;
  onToggleFav: (id: number) => void;
}

export default function TopicCard({ topic, isFav, onToggleFav }: TopicCardProps) {
  const [hovered, setHovered] = useState(false);
  const router = useRouter();

  return (
    <Panel
      onClick={() => router.push(`/topics/${topic.id}`)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cx('flex cursor-pointer flex-col gap-3.5 p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-gray-200 hover:shadow-lg', hovered && 'shadow-lg')}
    >
      {/* Header: level + categories */}
      <div className="flex flex-wrap items-center gap-2">
        <LevelBadge level={topic.recommendLevel} size="small" />
        {topic.categories.map((c) => (
          <span key={c} className="text-[11px] font-medium text-gray-400">
            {c}
          </span>
        ))}
      </div>

      {/* Title */}
      <h3 className="line-clamp-2 text-base font-semibold leading-6 text-gray-900">
        {topic.title}
      </h3>

      {/* Source + time */}
      <div className="text-xs text-gray-400">
        <span className="font-medium text-gray-500">{topic.source}</span>
        <span className="mx-1.5">·</span>
        <span>{topic.publishedAt}</span>
      </div>

      {/* Scores */}
      <div className="flex flex-col gap-1.5">
        <ScoreBar label="热度" value={topic.hotScore} />
        <ScoreBar label="价值" value={topic.creatorScore} />
      </div>

      {/* Reason */}
      <p className="line-clamp-2 text-[13px] leading-6 text-gray-500">
        {topic.reason}
      </p>

      {/* Footer: platforms + favorite */}
      <div className="mt-0.5 flex items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {topic.platforms.map((p) => (
            <PlatformTag key={p} name={p} />
          ))}
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleFav(topic.id);
          }}
          className={cx('inline-flex items-center border-0 bg-transparent p-1 transition', isFav ? 'text-primary' : 'text-gray-300 hover:text-primary')}
          aria-label={isFav ? '取消收藏' : '收藏'}
          aria-pressed={isFav}
          title={isFav ? '取消收藏' : '收藏'}
        >
          <Star size={18} strokeWidth={2} fill={isFav ? '#FF6B35' : 'none'} />
        </button>
      </div>
    </Panel>
  );
}
