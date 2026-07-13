'use client';

import { useCallback, useEffect, useState } from 'react';
import { Bookmark, CheckCircle2, Eye, XCircle, ExternalLink } from 'lucide-react';
import { Panel, cx } from '@/components/ui';
import { weeklyDigestApi } from '@/lib/api';

interface PickTrackMark {
  pick_title: string;
  action: 'write' | 'watch' | 'skip';
  mark_date: string;
  pick_category: string | null;
  appearances_in_week: number;
  appearance_dates: string[];
  pick_source_url: string | null;
}

const ACTION_META: Record<string, { label: string; icon: typeof Bookmark; color: string; bg: string }> = {
  write: { label: '已选', icon: CheckCircle2, color: 'text-primary', bg: 'bg-primary-light' },
  watch: { label: '观察', icon: Eye, color: 'text-amber', bg: 'bg-amber-light' },
  skip: { label: '跳过', icon: XCircle, color: 'text-gray-400', bg: 'bg-gray-100' },
};

/**
 * 周报的「选题追踪」段——展示用户本周在日报里标记过的选题，
 * 以及它们在几天日报的 top_picks 里持续出现。
 *
 * 金字塔压缩的独特价值：日报只看当天，周报看跨日持续性。
 */
export default function WeeklyPickTracking({ weekKey }: { weekKey: string | undefined }) {
  const [marks, setMarks] = useState<PickTrackMark[]>([]);
  const [loading, setLoading] = useState(true);
  const [weekRange, setWeekRange] = useState('');

  const fetch = useCallback(async () => {
    if (!weekKey) return;
    try {
      setLoading(true);
      const resp = await weeklyDigestApi.pickTracking(weekKey);
      setMarks(resp.marks);
      setWeekRange(resp.week_range);
    } catch {
      // 静默失败（游客无 token 等）
    } finally {
      setLoading(false);
    }
  }, [weekKey]);

  useEffect(() => {
    void fetch();
  }, [fetch]);

  if (loading) {
    return (
      <Panel className="mt-3 p-4">
        <div className="mb-2 text-sm font-black text-gray-700">选题追踪</div>
        <div className="text-xs text-gray-400">加载中...</div>
      </Panel>
    );
  }

  if (marks.length === 0) {
    return null; // 无标记时不显示此段
  }

  return (
    <Panel className="mt-3 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Bookmark size={15} className="text-primary" strokeWidth={2.2} />
        <span className="text-sm font-black text-gray-900">选题追踪</span>
        <span className="text-[11px] text-gray-400">· {weekRange}</span>
      </div>
      <p className="mb-3 text-[12px] leading-5 text-gray-500">
        本周你在日报里标记的选题，以下追踪它们在几天日报中持续上榜。
      </p>
      <div className="space-y-2">
        {marks.map((mark, i) => {
          const meta = ACTION_META[mark.action] || ACTION_META.watch;
          const Icon = meta.icon;
          const isPersistent = mark.appearances_in_week >= 2;
          return (
            <div
              key={`track-${i}`}
              className="flex items-start gap-3 rounded-md border border-gray-100 p-2.5"
            >
              {/* 标记类型 badge */}
              <div className={cx('flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold', meta.bg, meta.color)}>
                <Icon size={11} />
                {meta.label}
              </div>

              {/* 标题 + 追踪信息 */}
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-1.5">
                  <span className="flex-1 break-words text-[13px] font-bold leading-5 text-gray-800">
                    {mark.pick_title}
                  </span>
                  {mark.pick_source_url && (
                    <a
                      href={mark.pick_source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-0.5 shrink-0 text-gray-300 hover:text-primary"
                    >
                      <ExternalLink size={12} />
                    </a>
                  )}
                </div>
                <div className="mt-1 flex items-center gap-2 text-[10px] text-gray-400">
                  <span>标记于 {mark.mark_date}</span>
                  <span>·</span>
                  {isPersistent ? (
                    <span className="font-bold text-teal">在榜 {mark.appearances_in_week} 天 ↗</span>
                  ) : mark.appearances_in_week === 1 ? (
                    <span className="text-amber">仅 1 天上榜</span>
                  ) : (
                    <span className="text-gray-400">本周未上榜</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
