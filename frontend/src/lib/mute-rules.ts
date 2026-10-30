/**
 * 降噪规则（mute rules）的纯逻辑：类型口径、前端输入校验、分组。
 *
 * 校验口径与后端 mute_rule_service 对齐（keyword 1-100 字符；source 为
 * 信源 ID 数字；domain 归一为 host）。这里做提交前的即时反馈，最终以
 * 后端校验为准。
 */

import type { MuteRuleItem, MuteRuleType } from '@/lib/api/_mute-rules';

export type { MuteRuleType };

export const MUTE_RULE_TYPES: readonly MuteRuleType[] = ['keyword', 'source', 'domain'] as const;

export const MUTE_RULE_TYPE_LABELS: Record<MuteRuleType, string> = {
  keyword: '关键词',
  source: '信源',
  domain: '域名',
};

export const MUTE_RULE_TYPE_HINTS: Record<MuteRuleType, string> = {
  keyword: '标题或摘要包含该词的内容将被隐藏（1-100 字符）',
  source: '该信源（信源 ID，数字）的内容将被隐藏',
  domain: '该域名下的内容将被隐藏（自动去除 www. 前缀）',
};

export const MUTE_RULE_LIMIT_PER_TYPE = 50;

/** 校验输入值：返回 null 表示可提交，否则返回错误文案。 */
export function validateMuteRuleValue(type: MuteRuleType, rawValue: string): string | null {
  const value = rawValue.trim();
  if (!value) return '请输入内容';
  if (type === 'keyword') {
    if (value.length > 100) return '关键词最多 100 字符';
    return null;
  }
  if (type === 'source') {
    if (!/^\d+$/.test(value)) return '信源规则需填写信源 ID（数字）';
    return null;
  }
  // domain：允许粘贴完整链接，提取 host 后校验
  const host = normalizeDomainInput(value);
  if (!host) return '域名格式不正确，示例：example.com';
  if (/\s/.test(host)) return '域名不能包含空格';
  return null;
}

/** 与后端同口径的 domain 归一：去协议/路径/端口，小写，去 www. 前缀。 */
export function normalizeDomainInput(rawValue: string): string {
  let text = rawValue.trim().toLowerCase();
  if (text.includes('://')) text = text.split('://', 2)[1]!;
  text = text.split('/', 1)[0]!;
  text = text.split('?', 1)[0]!;
  text = text.split('#', 1)[0]!;
  text = text.split(':', 1)[0]!;
  if (text.startsWith('www.')) text = text.slice(4);
  return text;
}

/** 按类型分组（保持列表原有顺序），渲染三类分区用。 */
export function groupMuteRules(rules: MuteRuleItem[]): Record<MuteRuleType, MuteRuleItem[]> {
  const grouped: Record<MuteRuleType, MuteRuleItem[]> = { keyword: [], source: [], domain: [] };
  for (const rule of rules) {
    grouped[rule.rule_type].push(rule);
  }
  return grouped;
}

/** 是否允许继续添加该类型（上限 50）。 */
export function canAddMoreOfType(rules: MuteRuleItem[], type: MuteRuleType): boolean {
  return rules.filter((rule) => rule.rule_type === type).length < MUTE_RULE_LIMIT_PER_TYPE;
}
