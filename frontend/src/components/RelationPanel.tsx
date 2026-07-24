'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { GitBranch, List, Loader2, Network } from 'lucide-react';
import type { ContentRelation } from '@/types';
import { contentsApi } from '@/lib/api';
import { Badge, Panel, cx } from '@/components/ui';
import RelationGraph from '@/components/RelationGraph';

interface RelationPanelProps {
  contentId: number;
}

const RELATION_LABELS: Record<string, { label: string; color: string }> = {
  same_event: { label: '同事件', color: 'text-primary bg-primary-light/40' },
  related_topic: { label: '同话题', color: 'text-teal-text bg-teal-light' },
  temporal_cluster: { label: '同时段', color: 'text-amber bg-amber/10' },
  causal: { label: '因果', color: 'text-red bg-red-light' },
  response: { label: '回应', color: 'text-blue-500 bg-blue-50' },
  contrast: { label: '对比', color: 'text-purple-500 bg-purple-50' },
};

export default function RelationPanel({ contentId }: RelationPanelProps) {
  const [relations, setRelations] = useState<ContentRelation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'graph'>('list');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await contentsApi.getRelations(contentId);
      setRelations(result.relations);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
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
          加载关联内容...
        </div>
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel className="p-4">
        <div className="text-[13px] text-red">{error}</div>
      </Panel>
    );
  }

  if (relations.length === 0) {
    return null;
  }

  // Group by relation type
  const grouped: Record<string, ContentRelation[]> = {};
  for (const r of relations) {
    if (!grouped[r.relation_type]) grouped[r.relation_type] = [];
    grouped[r.relation_type].push(r);
  }

  return (
    <Panel className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch size={15} className="text-primary" />
          <span className="text-sm font-bold text-gray-800">关联内容</span>
          <span className="text-[11px] text-gray-400">({relations.length}条)</span>
        </div>
        <div className="flex items-center gap-1 rounded-md border border-gray-200 p-0.5">
          <button
            type="button"
            onClick={() => setViewMode('list')}
            className={cx('flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition', viewMode === 'list' ? 'bg-primary-light text-primary-text' : 'text-gray-500 hover:bg-gray-50')}
          >
            <List size={12} />
            列表
          </button>
          <button
            type="button"
            onClick={() => setViewMode('graph')}
            className={cx('flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition', viewMode === 'graph' ? 'bg-primary-light text-primary-text' : 'text-gray-500 hover:bg-gray-50')}
          >
            <Network size={12} />
            关系图
          </button>
        </div>
      </div>

      {viewMode === 'graph' ? (
        <RelationGraph contentId={contentId} contentTitle="当前内容" relations={relations} />
      ) : (
        <div className="space-y-3">
          {Object.entries(grouped).map(([type, items]) => {
            const meta = RELATION_LABELS[type] || { label: type, color: 'text-gray-600 bg-gray-100' };
            return (
              <div key={type}>
                <div className="mb-1.5 flex items-center gap-1.5">
                  <Badge className={cx('rounded px-2 py-0.5 text-[11px] font-bold', meta.color)}>
                    {meta.label}
                  </Badge>
                  <span className="text-[11px] text-gray-400">{items.length}条</span>
                </div>
                <div className="space-y-1">
                  {items.map((r) => (
                    <a
                      key={r.relation_id}
                      href={`/contents/${r.target_id}/reader`}
                      className="block rounded-md border border-gray-100 px-2.5 py-1.5 transition hover:border-primary-border hover:bg-primary-light/20"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="line-clamp-1 text-[13px] font-medium text-gray-800">
                          {r.target_title}
                        </span>
                        <span className="shrink-0 text-[10px] text-gray-400">
                          {r.target_source_name}
                        </span>
                      </div>
                      {r.evidence && (
                        <div className="mt-0.5 text-[10px] text-gray-400">{r.evidence}</div>
                      )}
                    </a>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
