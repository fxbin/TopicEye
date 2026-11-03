import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { DecisionOverview, DiagnosticsPanel, PathPanel } from './components';
import type { ScoringFlowResponse, ScoringFlowSample } from '@/lib/api';

const sample: ScoringFlowSample = {
  id: 1, title: '可解释的内容', url: '', source_name: '来源', category: '技术', selected: false,
  final_score: 45, threshold_used: 60, base_score: 70, source_bonus: 0,
  quality_factor: 1, risk_factor: 1, time_decay: 0.3, diversity_factor: 0,
  feedback_score: 0, dimension_scores: { info_density: 20 },
  raw_dimensions: { info_density: 80 }, dimension_weights: { info_density: 0.25 },
  analysis_source: 'local_fallback', review_status: 'pending', decision_reasons: ['等待模型复核，不占正式精选名额'],
};
const data = {
  total: 201, scored: 190, hours: 24, stages: [], samples: [sample], category_mix: [], source_mix: [],
  decision_context: { source: 'postgres', candidate_count: 201, filters: { event_members: 11 }, pool_size: 190, selected_count: 30, pending_review_count: 5, scope: 'today_picks', ranking: 'base_score_before_personalized_display' },
  diagnostics: { empty_reason: 'collected_not_analyzed', collected_window_total: 20, pending_analysis_total: 20, window_total: 0, window_options: [], loaded_count: 0, scoring_input_count: 0, scored_count: 0, analyzed_total: 0, ignored_count: 0, candidate_limit: 160, sample_limit: 80, generated_at: '' },
} as ScoringFlowResponse;

describe('真实精选解释', () => {
  it('区分原始80分、25%权重、20分贡献，并标记待复核', () => {
    const html = renderToStaticMarkup(<PathPanel sample={sample} onFeedback={vi.fn()} onFavorite={vi.fn()} onCreate={vi.fn()} feedbacking={false} />);
    expect(html).toContain('原始维度与加权贡献');
    expect(html).toContain('>80</span>');
    expect(html).toContain('>25%</span>');
    expect(html).toContain('>20.0</span>');
    expect(html).toContain('待模型复核');
    expect(html).toContain('等待模型复核，不占正式精选名额');
    expect(html).toContain('width:0%');
  });
  it('筛选数量与软降权分开，展示限制不会解释成候选截断', () => {
    const html = renderToStaticMarkup(<DecisionOverview data={data} />);
    expect(html).toContain('本次筛选与排序');
    expect(html).toContain('完整候选池');
    expect(html).toContain('201');
    expect(html).not.toContain('累计留存');
    expect(html).not.toContain('流失');
  });
  it('没有管理动作时不向普通用户展示后台分析按钮', () => {
    const html = renderToStaticMarkup(<DiagnosticsPanel data={{ ...data, scored: 0, samples: [] }} />);
    expect(html).not.toContain('分析最近内容');
    const admin = renderToStaticMarkup(<DiagnosticsPanel data={{ ...data, scored: 0, samples: [] }} onAnalyzePending={vi.fn()} />);
    expect(admin).toContain('分析最近内容');
  });
});
