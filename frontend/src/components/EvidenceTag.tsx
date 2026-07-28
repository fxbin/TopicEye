'use client';

import React from 'react';
import { Globe, ShieldCheck, Building2 } from 'lucide-react';
import type { EvidenceMark } from '@/types';
import { cx } from '@/components/ui';

interface EvidenceTagProps {
  /** Pre-loaded mark (from batch fetch) to avoid N+1 API calls */
  mark?: EvidenceMark | null;
}

export default function EvidenceTag({ mark }: EvidenceTagProps) {
  if (!mark || mark.cross_source_level === 'none') {
    return null;
  }

  const isStrong = mark.cross_source_level === 'strong_cross_source';
  const label = `${mark.platform_count} 来源报道`;

  return (
    <span className="inline-flex items-center gap-0.5">
      <span
        className={cx(
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold',
          isStrong ? 'bg-indigo-50 text-indigo-600' : 'bg-blue-50 text-blue-500',
        )}
        title={`来源线索，不代表事实核验。${mark.platforms.join('、')}`}
      >
        <Globe size={10} />
        {label}
      </span>
      {mark.has_primary_source && (
        <span
          className="inline-flex items-center gap-0.5 rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-600"
          title="事件原始发布者"
        >
          <ShieldCheck size={10} />
          原始
        </span>
      )}
      {mark.has_official_source && (
        <span
          className="inline-flex items-center gap-0.5 rounded-full bg-teal-50 px-1.5 py-0.5 text-[10px] font-bold text-teal-600"
          title="包含官方一手链接"
        >
          <Building2 size={10} />
          官方
        </span>
      )}
    </span>
  );
}
