'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { Globe } from 'lucide-react';
import { contentsApi } from '@/lib/api';
import type { EvidenceMark } from '@/types';
import { cx } from '@/components/ui';

interface EvidenceTagProps {
  contentId: number;
}

export default function EvidenceTag({ contentId }: EvidenceTagProps) {
  const [mark, setMark] = useState<EvidenceMark | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await contentsApi.getEvidence(contentId);
      setMark(result.evidence_mark);
    } catch {
      // silent fail — evidence is optional
    } finally {
      setLoaded(true);
    }
  }, [contentId]);

  useEffect(() => { load(); }, [load]);

  if (!loaded || !mark || mark.cross_source_level === 'none') {
    return null;
  }

  const isStrong = mark.cross_source_level === 'strong_cross_source';
  const label = `${mark.platform_count} 个来源报道`;

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
