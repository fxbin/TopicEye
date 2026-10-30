/**
 * 用户自定义降噪规则（mute rules）API。
 *
 * 后端 backend/app/api/v1/mute_rules.py：规则只影响当前用户可见的
 * contents 列表与 today-picks（排除命中项，不删除内容数据）。
 */

import { request } from './_core';

export type MuteRuleType = 'keyword' | 'source' | 'domain';

export interface MuteRuleItem {
  id: number;
  rule_type: MuteRuleType;
  value: string;
  created_at: string;
}

export interface MuteRuleListResponse {
  count: number;
  items: MuteRuleItem[];
}

export const muteRulesApi = {
  /** 列出当前用户的全量静音规则（新→旧）。 */
  list(): Promise<MuteRuleListResponse> {
    return request('/mute-rules');
  },

  /** 新增一条规则（每类上限 50，重复返回 409）。 */
  create(data: { rule_type: MuteRuleType; value: string }): Promise<MuteRuleItem> {
    return request('/mute-rules', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 删除自己的规则（不存在/他人规则返回 404）。 */
  remove(id: number): Promise<void> {
    return request(`/mute-rules/${id}`, { method: 'DELETE' });
  },
};
