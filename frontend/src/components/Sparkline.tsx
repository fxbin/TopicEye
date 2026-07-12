'use client';

import { cx } from '@/components/ui';

export interface SparklinePoint {
  ts: string;
  count: number;
  baseline?: number;
}

export interface SparklineData {
  points: SparklinePoint[];
  keywords: string[];
  total: number;
  window_hours: number;
}

/**
 * 极简折线图（sparkline）——展示选题近 N 小时的内容流入速率。
 *
 * 数据语义标注：这是「内容热度」（供应端：多少源在讨论），不是流量热度。
 * 用相对变化率而非绝对值渲染，避免不同选题因绝对量差异导致曲线失真。
 *
 * 实现要点：
 * - 纯 SVG，零依赖
 * - 24 个点 / 96px 宽 / 28px 高
 * - 用 baseline（均值）做归一化 baseline
 * - 颜色按"近期相对均值"自动分配：↑上升 teal，→平稳 amber，↓下降 gray
 */
export default function Sparkline({
  data,
  className,
  loading = false,
}: {
  data?: SparklineData;
  loading?: boolean;
  className?: string;
}) {
  if (loading) {
    return (
      <div className={cx('flex h-7 w-24 items-center justify-center rounded-xs bg-gray-50', className)}>
        <span className="text-[9px] text-gray-300">loading</span>
      </div>
    );
  }
  if (!data || !data.points || data.points.length === 0) {
    return (
      <div
        className={cx(
          'flex h-7 w-24 items-center justify-center rounded-xs border border-dashed border-gray-200 text-[9px] text-gray-300',
          className,
        )}
        title="暂无趋势数据"
      >
        no data
      </div>
    );
  }

  const points = data.points;
  const counts = points.map((p) => p.count);
  const max = Math.max(...counts, 1);
  // 用 baseline（如果后端有）或均值做归一化
  const baseline = data.points[0]?.baseline ?? max * 0.5;

  // 计算最近一段（最后 25%）相对均值的趋势方向
  const tail = counts.slice(Math.max(0, counts.length - Math.max(1, Math.floor(counts.length / 4))));
  const tailAvg = tail.length > 0 ? tail.reduce((a, b) => a + b, 0) / tail.length : 0;
  const overallAvg = counts.reduce((a, b) => a + b, 0) / Math.max(1, counts.length);
  const trendDir: 'up' | 'down' | 'flat' = tailAvg > overallAvg * 1.2 ? 'up' : tailAvg < overallAvg * 0.8 ? 'down' : 'flat';

  // SVG 几何
  const W = 96;
  const H = 28;
  const PAD_X = 2;
  const PAD_Y = 3;
  const stepX = (W - PAD_X * 2) / Math.max(1, points.length - 1);
  // y 归一化：0 = baseline（中间），max 接近顶部
  const yFor = (v: number) => {
    if (v >= baseline) {
      // 0 → H-PAD_Y (底部), max → PAD_Y (顶部)
      const t = (v - baseline) / Math.max(1, max - baseline);
      return H - PAD_Y - t * (H - PAD_Y * 2);
    } else {
      // baseline → H-PAD_Y，0 → H-PAD_Y+小偏移
      const t = (baseline - v) / Math.max(1, baseline);
      return H - PAD_Y + t * 4; // 0 部分最多下沉 4px
    }
  };
  const path = points
    .map((p, i) => {
      const x = PAD_X + i * stepX;
      const y = yFor(p.count);
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');

  // 趋势颜色
  const strokeColor = trendDir === 'up' ? '#14b8a6' : trendDir === 'down' ? '#9ca3af' : '#f59e0b';

  return (
    <div className={cx('flex items-center gap-1.5', className)} title={`近 ${data.window_hours}h 关键词: ${data.keywords.join(' / ')}, 总 ${data.total} 条`}>
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        className="shrink-0"
        aria-label={`${data.keywords.join(' / ')} 趋势`}
      >
        {/* baseline 中线 */}
        <line
          x1={PAD_X}
          y1={H - PAD_Y}
          x2={W - PAD_X}
          y2={H - PAD_Y}
          stroke="#e5e7eb"
          strokeWidth="0.5"
          strokeDasharray="2 2"
        />
        <path d={path} fill="none" stroke={strokeColor} strokeWidth="1.2" strokeLinejoin="round" strokeLinecap="round" />
        {/* 端点高亮 */}
        {points.length > 0 && (
          <circle
            cx={PAD_X + (points.length - 1) * stepX}
            cy={yFor(counts[counts.length - 1])}
            r="1.6"
            fill={strokeColor}
          />
        )}
      </svg>
      <span className="text-[10px] font-bold text-gray-400">{data.total}</span>
    </div>
  );
}
