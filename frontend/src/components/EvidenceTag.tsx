'use client';

import React from 'react';
import { Globe } from 'lucide-react';
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
  );
}
