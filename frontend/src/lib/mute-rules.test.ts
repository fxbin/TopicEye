import { describe, expect, it } from 'vitest';
import {
  MUTE_RULE_TYPES,
  MUTE_RULE_TYPE_LABELS,
  canAddMoreOfType,
  groupMuteRules,
  normalizeDomainInput,
  validateMuteRuleValue,
} from './mute-rules';
import type { MuteRuleItem } from '@/lib/api/_mute-rules';

const rule = (id: number, rule_type: MuteRuleItem['rule_type'], value: string): MuteRuleItem => ({
  id,
  rule_type,
  value,
  created_at: '2026-10-27T10:00:00+00:00',
});

describe('validateMuteRuleValue', () => {
  it('rejects blank input for every type', () => {
    for (const type of MUTE_RULE_TYPES) {
      expect(validateMuteRuleValue(type, '   ')).not.toBeNull();
    }
  });

  it('keyword accepts 1-100 chars and rejects longer', () => {
    expect(validateMuteRuleValue('keyword', ' 静音词 ')).toBeNull();
    expect(validateMuteRuleValue('keyword', 'a'.repeat(100))).toBeNull();
    expect(validateMuteRuleValue('keyword', 'a'.repeat(101))).toMatchInlineSnapshot(`"关键词最多 100 字符"`);
  });

  it('source only accepts numeric source ids', () => {
    expect(validateMuteRuleValue('source', '42')).toBeNull();
    expect(validateMuteRuleValue('source', 'example.com')).toMatchInlineSnapshot(`"信源规则需填写信源 ID（数字）"`);
  });

  it('domain accepts bare hosts and full urls', () => {
    expect(validateMuteRuleValue('domain', 'example.com')).toBeNull();
    expect(validateMuteRuleValue('domain', 'https://www.Example.com/a?b=1')).toBeNull();
    expect(validateMuteRuleValue('domain', 'bad domain')).not.toBeNull();
  });
});

describe('normalizeDomainInput', () => {
  it('strips scheme, path, query, port and www prefix, lowercases', () => {
    expect(normalizeDomainInput('https://WWW.Example.com:8080/path?q=1')).toBe('example.com');
    expect(normalizeDomainInput('www.noisy.example.com')).toBe('noisy.example.com');
    expect(normalizeDomainInput('example.com')).toBe('example.com');
  });

  it('does not strip hosts that merely start with www', () => {
    expect(normalizeDomainInput('wwwexample.com')).toBe('wwwexample.com');
  });
});

describe('groupMuteRules', () => {
  it('buckets rules by type while keeping order', () => {
    const grouped = groupMuteRules([
      rule(1, 'keyword', 'a'),
      rule(2, 'domain', 'x.com'),
      rule(3, 'keyword', 'b'),
      rule(4, 'source', '7'),
    ]);
    expect(grouped.keyword.map((item) => item.value)).toEqual(['a', 'b']);
    expect(grouped.domain.map((item) => item.value)).toEqual(['x.com']);
    expect(grouped.source.map((item) => item.value)).toEqual(['7']);
  });

  it('returns empty buckets for empty input', () => {
    const grouped = groupMuteRules([]);
    expect(Object.keys(grouped).sort()).toEqual([...MUTE_RULE_TYPES].sort());
    expect(grouped.keyword).toEqual([]);
  });
});

describe('canAddMoreOfType', () => {
  it('blocks the 51st rule of a type but not other types', () => {
    const rules = Array.from({ length: 50 }, (_, i) => rule(i + 1, 'keyword', `kw-${i}`));
    expect(canAddMoreOfType(rules, 'keyword')).toBe(false);
    expect(canAddMoreOfType(rules, 'domain')).toBe(true);
    expect(canAddMoreOfType(rules.slice(0, 49), 'keyword')).toBe(true);
  });
});

describe('type label coverage', () => {
  it('has labels for every type', () => {
    for (const type of MUTE_RULE_TYPES) {
      expect(MUTE_RULE_TYPE_LABELS[type].length).toBeGreaterThan(0);
    }
  });
});
