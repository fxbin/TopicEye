/**
 * 评分拆解可视化（独立可复用组件）。
 *
 * 从 ContentAnalysisPanel 抽出，供 today-picks 卡片轻量展示评分解释。
 * 输入后端 ScoreBreakdown（见 backend/app/services/scoring_engine.py:104）。
 */
'use client';

import type { ScoreBreakdown as ScoreBreakdownType } from '@/types';

const DIMENSION_LABELS: Record<string, { label: string; color: string }> = {
  info_density: { label: '信息密度', color: '#3b82f6' },
  actionability: { label: '可操作性', color: '#8b5cf6' },
  creator_value: { label: '创作者价值', color: '#6366f1' },
  viral_potential: { label: '爆文潜力', color: '#ef4444' },
  source_authority: { label: '来源权威', color: '#f59e0b' },
  freshness: { label: '时效新鲜', color: '#10b981' },
};

export default function ScoreBreakdownChart({ breakdown }: { breakdown: ScoreBreakdownType }) {
  const dims = breakdown.dimension_scores || {};
  const factors = [
    { label: '来源加权', value: breakdown.source_bonus, max: 20, color: '#f59e0b' },
    { label: '时效衰减', value: breakdown.time_decay * 100, max: 100, color: '#10b981', suffix: '%' },
    { label: '多样性', value: breakdown.diversity_factor * 100, max: 100, color: '#6366f1', suffix: '%' },
  ];

  return (
    <div>
      {/* 6-dimension weighted contribution bars */}
      <div className="mb-4 flex flex-col gap-2.5">
        {Object.entries(DIMENSION_LABELS).map(([key, meta]) => {
          const raw = dims[key] || 0;
          const pct = Math.min(100, (raw / 25) * 100);
          return (
            <div key={key} className="flex items-center gap-2.5">
              <span className="w-[72px] shrink-0 text-right text-xs text-gray-600">
                {meta.label}
              </span>
              <div className="h-2 flex-1 overflow-hidden rounded bg-gray-100">
                <div
                  style={{ width: `${pct}%`, background: meta.color }}
                  className="h-full rounded transition-[width] duration-500"
                />
              </div>
              <span className="w-8 text-right font-mono text-[11px] text-gray-500">
                {raw.toFixed(1)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Adjustment factors */}
      <div className="flex gap-4 rounded-lg border border-gray-100 bg-gray-50 px-3.5 py-2.5">
        {factors.map((f) => (
          <div key={f.label} className="flex-1 text-center">
            <div className="font-mono text-base font-bold" style={{ color: f.color }}>
              {f.suffix ? `${Math.round(f.value)}${f.suffix}` : (f.value > 0 ? `+${f.value.toFixed(0)}` : f.value.toFixed(0))}
            </div>
            <div className="mt-0.5 text-[10px] text-gray-400">{f.label}</div>
          </div>
        ))}
      </div>

      {/* Final score */}
      <div className="mt-3 flex items-center justify-between rounded-lg bg-primary-light px-4 py-3">
        <span className="text-[13px] font-medium text-gray-600">最终精选分</span>
        <span className="font-mono text-[22px] font-extrabold text-primary">
          {breakdown.final_score.toFixed(1)}
        </span>
      </div>
    </div>
  );
}

export { DIMENSION_LABELS };
