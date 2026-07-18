/**
 * Product feedback 共享标签与色调映射。
 *
 * 历史上 `app/feedback/page.tsx` 与 `app/changelog/page.tsx` 各有一份标签映射，
 * 且部分值冲突（R9 bug）：
 * - UPDATE_KIND_LABELS.improvement: changelog='改进' vs feedback='优化'
 * - UPDATE_STATUS_LABELS.planned: changelog='已规划' vs feedback='计划中'
 * - UPDATE_STATUS_TONES.planned: changelog='amber' vs feedback='neutral'
 * - SEVERITY_TONES.high: changelog='red' vs feedback='amber'
 *
 * 本模块统一权威值（取 changelog 版，因其更正式），修复冲突。
 * feedback / changelog 两页统一 import 本模块，消除重复定义。
 */

import type { Tone } from '@/components/ui';
import type {
  IssueFeedbackStatus,
  IssueFeedbackSeverity,
  ProductUpdateKind,
  ProductUpdateStatus,
} from '@/lib/api';

// ── Issue feedback status ────────────────────────────────────────────

export const ISSUE_STATUS_LABELS: Record<IssueFeedbackStatus, string> = {
  open: '待处理',
  triaged: '已确认',
  in_progress: '处理中',
  fixed: '已修复',
  closed: '已关闭',
};

export const ISSUE_STATUS_TONES: Record<IssueFeedbackStatus, Tone> = {
  open: 'amber',
  triaged: 'primary',
  in_progress: 'purple',
  fixed: 'teal',
  closed: 'neutral',
};

// ── Issue feedback severity ──────────────────────────────────────────

export const SEVERITY_LABELS: Record<IssueFeedbackSeverity, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
};

export const SEVERITY_TONES: Record<IssueFeedbackSeverity, Tone> = {
  low: 'neutral',
  medium: 'primary',
  high: 'red',
  critical: 'red',
};

// ── Product update kind ──────────────────────────────────────────────

export const UPDATE_KIND_LABELS: Record<ProductUpdateKind, string> = {
  release: '发布',
  improvement: '改进',
  fix: '修复',
  roadmap: '规划',
};

export const UPDATE_KIND_TONES: Record<ProductUpdateKind, Tone> = {
  release: 'teal',
  improvement: 'primary',
  fix: 'purple',
  roadmap: 'amber',
};

// ── Product update status ────────────────────────────────────────────

export const UPDATE_STATUS_LABELS: Record<ProductUpdateStatus, string> = {
  planned: '已规划',
  in_progress: '进行中',
  shipped: '已发布',
};

export const UPDATE_STATUS_TONES: Record<ProductUpdateStatus, Tone> = {
  planned: 'amber',
  in_progress: 'primary',
  shipped: 'teal',
};
