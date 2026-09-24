import type { ContentAnalysis, RecommendLevel } from '@/types';

export type RecommendationSignalQuality = 'ready' | 'weak' | 'missing';

export interface RecommendationDecision {
  level: RecommendLevel;
  reason: string;
  signalQuality: RecommendationSignalQuality;
  signals: string[];
}

const SCORE_KEYS: Array<keyof Pick<
  ContentAnalysis,
  'quality_score' | 'hot_score' | 'freshness_score' | 'creator_score' | 'viral_score' | 'risk_score'
>> = [
  'quality_score',
  'hot_score',
  'freshness_score',
  'creator_score',
  'viral_score',
  'risk_score',
];

function score(analysis: ContentAnalysis, key: typeof SCORE_KEYS[number]): number {
  const value = analysis[key];
  return Number.isFinite(value) ? Number(value) : 0;
}

function isDefaultScoreProfile(analysis: ContentAnalysis): boolean {
  const defaultLikeCount = SCORE_KEYS.filter((key) => score(analysis, key) === 50).length;
  const hasCuration = (analysis.adjusted_curation_score || analysis.curation_score || 0) > 0;
  const hasTextSignal = Boolean(
    analysis.recommended_reason ||
    analysis.recommendation ||
    analysis.summary ||
    analysis.key_points?.length ||
    analysis.creator_angles?.length,
  );
  return defaultLikeCount >= 5 && !hasCuration && !hasTextSignal;
}

// 与后端评分引擎对齐的门槛（backend/app/services/scoring_engine.py CONFIG）：
// risk_threshold=82 硬排除；quality_gate_min=45 内容过薄下限。
// 规则顺序：先过统一的风险/质量/创作价值门槛，再判断推荐类型，
// 避免「质量 10 + 创作价值 90」被判为强烈建议写、「风险 95 + 热度 90」
// 被判为适合蹭热点这类后端根本不会收录的推荐口径。
const RISK_HARD_EXCLUDE = 82;
const RISK_HIGH = 75;
const QUALITY_GATE_MIN = 45;

export function explainRecommendation(analysis: ContentAnalysis | null | undefined): RecommendationDecision {
  if (!analysis) {
    return {
      level: '信号不足',
      signalQuality: 'missing',
      reason: '尚未完成 AI 分析，当前只能作为原始素材浏览，不应视为已推荐选题。',
      signals: ['无评分', '无推荐理由'],
    };
  }

  const qualityScore = score(analysis, 'quality_score');
  const hotScore = score(analysis, 'hot_score');
  const freshnessScore = score(analysis, 'freshness_score');
  const creatorScore = score(analysis, 'creator_score');
  const viralScore = score(analysis, 'viral_score');
  const riskScore = score(analysis, 'risk_score');
  const curationScore = analysis.adjusted_curation_score ?? analysis.curation_score ?? 0;

  if (isDefaultScoreProfile(analysis)) {
    return {
      level: '信号不足',
      signalQuality: 'weak',
      reason: '多维评分仍停留在默认 50，缺少热度、创作价值和风险的有效判断，暂不归入“值得观察”。',
      signals: ['默认分过多', '缺少解释文本'],
    };
  }

  if (riskScore >= RISK_HARD_EXCLUDE) {
    return {
      level: '不建议追',
      signalQuality: 'ready',
      reason: `风险 ${Math.round(riskScore)} 超过硬性排除线 ${RISK_HARD_EXCLUDE}，后端精选流不会收录此类内容，不建议投入。`,
      signals: [`风险 ${Math.round(riskScore)}`, `超过排除线 ${RISK_HARD_EXCLUDE}`],
    };
  }

  if (creatorScore < 50 || riskScore >= RISK_HIGH) {
    return {
      level: '不建议追',
      signalQuality: 'ready',
      reason: creatorScore < 50
        ? `创作价值 ${Math.round(creatorScore)} 低于 50，投入产出不明确。`
        : `风险 ${Math.round(riskScore)} 偏高，暂不建议直接追。`,
      signals: [`创作价值 ${Math.round(creatorScore)}`, `风险 ${Math.round(riskScore)}`],
    };
  }

  if (qualityScore < QUALITY_GATE_MIN) {
    return {
      level: '不建议追',
      signalQuality: 'ready',
      reason: `质量 ${Math.round(qualityScore)} 低于内容门槛 ${QUALITY_GATE_MIN}，信息量不足以支撑成稿判断。`,
      signals: [`质量 ${Math.round(qualityScore)}`, `低于门槛 ${QUALITY_GATE_MIN}`],
    };
  }

  if (creatorScore >= 85 && riskScore <= 40) {
    return {
      level: '强烈建议写',
      signalQuality: 'ready',
      reason: `创作价值 ${Math.round(creatorScore)}，风险 ${Math.round(riskScore)}，适合作为优先成稿选题。`,
      signals: [`创作价值 ${Math.round(creatorScore)}`, `风险 ${Math.round(riskScore)}`],
    };
  }

  if (hotScore >= 80 && riskScore > 40) {
    return {
      level: '适合蹭热点',
      signalQuality: 'ready',
      reason: `热度 ${Math.round(hotScore)} 但风险 ${Math.round(riskScore)}，适合做热点跟进，发布前需要控制表达边界。`,
      signals: [`热度 ${Math.round(hotScore)}`, `风险 ${Math.round(riskScore)}`],
    };
  }

  if (qualityScore >= 85 && freshnessScore < 50) {
    return {
      level: '适合深挖',
      signalQuality: 'ready',
      reason: `质量 ${Math.round(qualityScore)}，但新鲜度 ${Math.round(freshnessScore)}，更适合做背景解释、拆解或观点深挖。`,
      signals: [`质量 ${Math.round(qualityScore)}`, `新鲜度 ${Math.round(freshnessScore)}`],
    };
  }

  if (creatorScore >= 70 && hotScore >= 70 && riskScore <= 60) {
    return {
      level: '值得观察',
      signalQuality: 'ready',
      reason: `创作价值 ${Math.round(creatorScore)}、热度 ${Math.round(hotScore)} 均达到观察线，风险 ${Math.round(riskScore)} 可控。`,
      signals: [`创作价值 ${Math.round(creatorScore)}`, `热度 ${Math.round(hotScore)}`, `风险 ${Math.round(riskScore)}`],
    };
  }

  return {
    level: '信号不足',
    signalQuality: curationScore > 0 || viralScore > 0 ? 'weak' : 'missing',
    reason: `当前分数没有触发明确推荐规则：创作 ${Math.round(creatorScore)}、热度 ${Math.round(hotScore)}、质量 ${Math.round(qualityScore)}、风险 ${Math.round(riskScore)}。建议先补充分析或等待更多传播信号。`,
    signals: [`创作 ${Math.round(creatorScore)}`, `热度 ${Math.round(hotScore)}`, `质量 ${Math.round(qualityScore)}`, `风险 ${Math.round(riskScore)}`],
  };
}

export function getRecommendationReason(analysis: ContentAnalysis | null | undefined, fallback?: string | null): string {
  const modelReason = analysis?.recommendation || analysis?.recommended_reason;
  if (modelReason && modelReason.trim()) return modelReason;
  return explainRecommendation(analysis).reason || fallback || '';
}
