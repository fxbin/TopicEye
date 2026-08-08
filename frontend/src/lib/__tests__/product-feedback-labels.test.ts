import { describe, it, expect } from 'vitest';
import {
  ISSUE_STATUS_LABELS,
  ISSUE_STATUS_TONES,
  SEVERITY_LABELS,
  SEVERITY_TONES,
  UPDATE_KIND_LABELS,
  UPDATE_KIND_TONES,
  UPDATE_STATUS_LABELS,
  UPDATE_STATUS_TONES,
} from '@/lib/product-feedback-labels';

describe('ISSUE_STATUS_LABELS', () => {
  it('maps all issue statuses', () => {
    expect(ISSUE_STATUS_LABELS.open).toBe('待处理');
    expect(ISSUE_STATUS_LABELS.triaged).toBe('已确认');
    expect(ISSUE_STATUS_LABELS.in_progress).toBe('处理中');
    expect(ISSUE_STATUS_LABELS.fixed).toBe('已修复');
    expect(ISSUE_STATUS_LABELS.closed).toBe('已关闭');
  });
});

describe('ISSUE_STATUS_TONES', () => {
  it('assigns tones to all issue statuses', () => {
    expect(ISSUE_STATUS_TONES.open).toBe('amber');
    expect(ISSUE_STATUS_TONES.triaged).toBe('primary');
    expect(ISSUE_STATUS_TONES.in_progress).toBe('purple');
    expect(ISSUE_STATUS_TONES.fixed).toBe('teal');
    expect(ISSUE_STATUS_TONES.closed).toBe('neutral');
  });
});

describe('SEVERITY_LABELS', () => {
  it('maps all severity levels', () => {
    expect(SEVERITY_LABELS.low).toBe('低');
    expect(SEVERITY_LABELS.medium).toBe('中');
    expect(SEVERITY_LABELS.high).toBe('高');
    expect(SEVERITY_LABELS.critical).toBe('严重');
  });
});

describe('SEVERITY_TONES', () => {
  it('assigns red tone to high and critical', () => {
    expect(SEVERITY_TONES.high).toBe('red');
    expect(SEVERITY_TONES.critical).toBe('red');
  });

  it('assigns non-red tones to low and medium', () => {
    expect(SEVERITY_TONES.low).toBe('neutral');
    expect(SEVERITY_TONES.medium).toBe('primary');
  });
});

describe('UPDATE_KIND_LABELS', () => {
  it('maps all update kinds', () => {
    expect(UPDATE_KIND_LABELS.release).toBe('发布');
    expect(UPDATE_KIND_LABELS.improvement).toBe('改进');
    expect(UPDATE_KIND_LABELS.fix).toBe('修复');
    expect(UPDATE_KIND_LABELS.roadmap).toBe('规划');
  });
});

describe('UPDATE_KIND_TONES', () => {
  it('assigns distinct tones to each kind', () => {
    expect(UPDATE_KIND_TONES.release).toBe('teal');
    expect(UPDATE_KIND_TONES.improvement).toBe('primary');
    expect(UPDATE_KIND_TONES.fix).toBe('purple');
    expect(UPDATE_KIND_TONES.roadmap).toBe('amber');
  });
});

describe('UPDATE_STATUS_LABELS', () => {
  it('maps all update statuses', () => {
    expect(UPDATE_STATUS_LABELS.planned).toBe('已规划');
    expect(UPDATE_STATUS_LABELS.in_progress).toBe('进行中');
    expect(UPDATE_STATUS_LABELS.shipped).toBe('已发布');
  });
});

describe('UPDATE_STATUS_TONES', () => {
  it('assigns tones to all update statuses', () => {
    expect(UPDATE_STATUS_TONES.planned).toBe('amber');
    expect(UPDATE_STATUS_TONES.in_progress).toBe('primary');
    expect(UPDATE_STATUS_TONES.shipped).toBe('teal');
  });
});
