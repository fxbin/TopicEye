'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { Globe, Loader2 } from 'lucide-react';
import { contentsApi } from '@/lib/api';
import type { EvidenceMark, EvidenceLink } from '@/types';
import { Panel, cx } from '@/components/ui';

interface EvidencePanelProps {
  contentId: number;
}

const LEVEL_LABELS: Record<string, { label: string; color: string }> = {
  cross_source: { label: '跨源信号', color: 'text-blue-500 bg-blue-50' },
  strong_cross_source: { label: '强跨源信号', color: 'text-indigo-600 bg-indigo-50' },
};

const TYPE_LABELS: Record<string, string> = {
  cross_source: '跨源报道',
  primary_source: '原始发布',
  official_link: '官方一手链接',
  independent_report: '独立报道',
};

export default function EvidencePanel({ contentId }: EvidencePanelProps) {
  const [mark, setMark] = useState<EvidenceMark | null>(null);
  const [links, setLinks] = useState<EvidenceLink[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await contentsApi.getEvidence(contentId);
      setMark(result.evidence_mark);
      setLinks(result.evidence_links || []);
    } catch {
      // silent — evidence is optional
    } finally {
      setLoading(false);
    }
  }, [contentId]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <Panel className="p-4">
        <div className="flex items-center gap-2 text-[13px] text-gray-400">
          <Loader2 size={16} className="animate-spin" />
          加载来源证据...
        </div>
      </Panel>
    );
  }

  if (!mark || mark.cross_source_level === 'none') {
    return null;
  }

  const meta = LEVEL_LABELS[mark.cross_source_level] || { label: mark.cross_source_level, color: 'text-gray-600 bg-gray-100' };

  return (
    <Panel className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <Globe size={15} className="text-indigo-500" />
        <span className="text-sm font-bold text-gray-800">来源与可信线索</span>
        <span className={cx('rounded px-2 py-0.5 text-[11px] font-bold', meta.color)}>
          {meta.label}
        </span>
        <span className="text-[11px] text-gray-400">
          {mark.platform_count} 平台 · {mark.evidence_count} 条证据
        </span>
      </div>

      {links.length > 0 && (
        <div className="space-y-1">
          {links.map((link, i) => (
            <div
              key={i}
              className="flex items-center justify-between gap-2 rounded-md border border-gray-100 px-2.5 py-1.5"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-bold text-gray-500">
                    {TYPE_LABELS[link.evidence_type] || link.evidence_type}
                  </span>
                  <span className="text-[12px] text-gray-600">
                    {link.publisher_family || '未知来源'}
                  </span>
                  {link.match_basis && (
                    <span className="text-[10px] text-gray-300">
                      ({link.match_basis})
                    </span>
                  )}
                </div>
              </div>
              {link.evidence_url && (
                <a
                  href={link.evidence_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 text-[10px] font-bold text-primary hover:underline"
                >
                  查看原文
                </a>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-2 text-[10px] text-gray-400">
        这些是可追溯的来源线索，不代表平台已完成事实核验。
      </div>
    </Panel>
  );
}
