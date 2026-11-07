import React from 'react';
import { Columns3, List } from 'lucide-react';
import { Button } from '@/components/ui';

export function PicksViewMode({ grouped, topicCount, itemCount, loading, onChange }: {
  grouped: boolean;
  topicCount: number;
  itemCount: number;
  loading: boolean;
  onChange: (grouped: boolean) => void;
}) {
  const unavailable = !loading && itemCount > 0 && topicCount === 0;
  return (
    <div className="flex max-w-full flex-col items-end gap-1.5">
      <div role="group" aria-label="精选展示方式" className="flex gap-1.5">
        <Button type="button" variant={grouped ? 'secondary' : 'primary'} aria-pressed={!grouped} disabled={loading} onClick={() => onChange(false)}>
          <List size={15} />精选列表
        </Button>
        <Button type="button" variant={grouped ? 'primary' : 'secondary'} aria-pressed={grouped} disabled={loading || topicCount === 0} aria-describedby={unavailable ? 'picks-grouping-help' : undefined} onClick={() => onChange(true)}>
          <Columns3 size={15} />精选分组
        </Button>
      </div>
      {unavailable && <p id="picks-grouping-help" className="text-xs leading-5 text-gray-600">已加载的精选暂无话题分组，按评分展示。</p>}
    </div>
  );
}
