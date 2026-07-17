import { describe, it, expect } from 'vitest';
import type { ContentAnalysis } from '@/types';
import { explainRecommendation, getRecommendationReason } from '@/lib/recommendation';

// 纯逻辑测试：用最小字段构造 ContentAnalysis，其余必填字段与本决策无关，
// 统一用 `as unknown as ContentAnalysis` 断言，避免为无关字段堆样板。
const analysis = (o: Record<string, unknown>): ContentAnalysis => o as unknown as ContentAnalysis;

describe('explainRecommendation', () => {
  it('analysis 为空时返回「信号不足 / missing」', () => {
    const d = explainRecommendation(null);
    expect(d.level).toBe('信号不足');
    expect(d.signalQuality).toBe('missing');
  });

  it('多维评分全为默认 50 且无文本信号 → 「信号不足 / weak」', () => {
    const d = explainRecommendation(
      analysis({
        quality_score: 50,
        hot_score: 50,
        freshness_score: 50,
        creator_score: 50,
        viral_score: 50,
        risk_score: 50,
      }),
    );
    expect(d.level).toBe('信号不足');
    expect(d.signalQuality).toBe('weak');
  });

  it('创作价值高且风险低 → 「强烈建议写」', () => {
    const d = explainRecommendation(
      analysis({ quality_score: 60, hot_score: 60, freshness_score: 60, creator_score: 90, viral_score: 60, risk_score: 20 }),
    );
    expect(d.level).toBe('强烈建议写');
    expect(d.signalQuality).toBe('ready');
  });

  it('热度高但风险偏高 → 「适合蹭热点」', () => {
    const d = explainRecommendation(
      analysis({ quality_score: 60, hot_score: 85, freshness_score: 60, creator_score: 60, viral_score: 60, risk_score: 55 }),
    );
    expect(d.level).toBe('适合蹭热点');
  });

  it('质量高但新鲜度低 → 「适合深挖」', () => {
    const d = explainRecommendation(
      analysis({ quality_score: 90, hot_score: 60, freshness_score: 30, creator_score: 60, viral_score: 60, risk_score: 30 }),
    );
    expect(d.level).toBe('适合深挖');
  });

  it('创作与热度均达观察线且风险可控 → 「值得观察」', () => {
    const d = explainRecommendation(
      analysis({ quality_score: 60, hot_score: 75, freshness_score: 60, creator_score: 75, viral_score: 60, risk_score: 45 }),
    );
    expect(d.level).toBe('值得观察');
  });

  it('创作价值过低 → 「不建议追」', () => {
    const d = explainRecommendation(
      analysis({ quality_score: 30, hot_score: 30, freshness_score: 60, creator_score: 40, viral_score: 10, risk_score: 30 }),
    );
    expect(d.level).toBe('不建议追');
    expect(d.reason).toContain('创作价值');
  });

  it('风险过高 → 「不建议追」（风险分支）', () => {
    const d = explainRecommendation(
      analysis({ quality_score: 30, hot_score: 30, freshness_score: 60, creator_score: 60, viral_score: 60, risk_score: 80 }),
    );
    expect(d.level).toBe('不建议追');
    expect(d.reason).toContain('风险');
  });

  it('未触发任何规则且有传播信号 → 「信号不足 / weak」', () => {
    const d = explainRecommendation(
      analysis({ quality_score: 55, hot_score: 55, freshness_score: 55, creator_score: 55, viral_score: 60, risk_score: 55 }),
    );
    expect(d.level).toBe('信号不足');
    expect(d.signalQuality).toBe('weak');
  });

  it('未触发任何规则且无任何信号 → 「信号不足 / missing」', () => {
    const d = explainRecommendation(
      analysis({ quality_score: 55, hot_score: 55, freshness_score: 55, creator_score: 55, viral_score: 0, risk_score: 55 }),
    );
    expect(d.level).toBe('信号不足');
    expect(d.signalQuality).toBe('missing');
  });
});

describe('getRecommendationReason', () => {
  it('优先返回模型给出的 recommendation', () => {
    const reason = getRecommendationReason(analysis({ recommendation: '模型推荐语' }));
    expect(reason).toBe('模型推荐语');
  });

  it('无 recommendation 时回退到 recommended_reason', () => {
    const reason = getRecommendationReason(analysis({ recommended_reason: '推荐理由' }));
    expect(reason).toBe('推荐理由');
  });

  it('无模型文本时回退到规则解释', () => {
    const reason = getRecommendationReason(
      analysis({ quality_score: 60, hot_score: 60, freshness_score: 60, creator_score: 90, viral_score: 60, risk_score: 20 }),
    );
    expect(reason).toContain('创作价值');
  });

  it('analysis 为空时回退到规则解释（reason 非空则不用 fallback）', () => {
    const reason = getRecommendationReason(null, '兜底文案');
    expect(reason).toContain('AI 分析');
  });
});
