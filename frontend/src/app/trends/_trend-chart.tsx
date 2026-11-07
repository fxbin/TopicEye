import React from 'react';
import type { TrendPoint } from '@/types/trends';

export function TrendChart({ dates, points, selectedDate, name }: { dates: string[]; points: TrendPoint[]; selectedDate: string; name: string }) {
  const values = dates.map(date => points.find(point => point.date === date));
  const max = Math.max(...points.map(point => point.content_count), 1);
  const x = (index: number) => dates.length === 1 ? 140 : 16 + index * 248 / (dates.length - 1);
  const y = (count: number) => 55 - count / max * 43;
  return <svg role="img" aria-label={`${name}每日内容数量，空缺表示没有快照`} viewBox="0 0 280 82" className="block h-[74px] w-full">
    <desc>{values.map((point, i) => `${dates[i]}：${point ? `${point.content_count}条` : '无快照'}`).join('；')}</desc>
    <line x1="16" x2="264" y1="55" y2="55" stroke="#E5E7EB" />
    {values.map((point, index) => {
      if (!point) return null;
      const previous = values[index - 1];
      const comparable = previous && !!point.calculation_version?.trim() && previous.calculation_version === point.calculation_version;
      return <g key={point.date}>
        {comparable && <line data-trend-segment="true" x1={x(index - 1)} x2={x(index)} y1={y(previous.content_count)} y2={y(point.content_count)} stroke="#9CA3AF" strokeWidth="2" />}
        <circle cx={x(index)} cy={y(point.content_count)} r={point.date === selectedDate ? 4.5 : 3} fill={point.date === selectedDate ? '#FF6B35' : '#9CA3AF'}><title>{point.date}：{point.content_count}条</title></circle>
      </g>;
    })}
    <text x="16" y="77" fontSize="12" fill="#6B7280">{dates[0]?.slice(5).replace('-', '/')}</text>
    {dates.length > 1 && <text x="264" y="77" fontSize="12" textAnchor="end" fill="#6B7280">{dates.at(-1)?.slice(5).replace('-', '/')}</text>}
  </svg>;
}
