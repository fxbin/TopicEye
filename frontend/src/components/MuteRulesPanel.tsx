'use client';

/**
 * 个人中心「降噪规则」面板（#171）。
 *
 * 三类规则（关键词 / 信源 / 域名）的列表 / 添加 / 删除。规则只影响当前
 * 用户的内容列表与今日精选；校验与上限口径见 @/lib/mute-rules。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, Plus, Trash2, VolumeX } from 'lucide-react';
import { Badge, Button, Panel, cx } from '@/components/ui';
import { FieldLabel, Select, TextInput } from '@/components/form';
import { muteRulesApi } from '@/lib/api';
import type { MuteRuleItem } from '@/lib/api';
import {
  MUTE_RULE_TYPES,
  MUTE_RULE_TYPE_HINTS,
  MUTE_RULE_TYPE_LABELS,
  canAddMoreOfType,
  groupMuteRules,
  validateMuteRuleValue,
} from '@/lib/mute-rules';
import type { MuteRuleType } from '@/lib/mute-rules';
import { formatDateTime } from '@/lib/datetime';

const TYPE_BADGE_TONE: Record<MuteRuleType, 'primary' | 'teal' | 'purple'> = {
  keyword: 'primary',
  source: 'teal',
  domain: 'purple',
};

export default function MuteRulesPanel() {
  const [rules, setRules] = useState<MuteRuleItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [inputType, setInputType] = useState<MuteRuleType>('keyword');
  const [inputValue, setInputValue] = useState('');
  const [adding, setAdding] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const loadRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await muteRulesApi.list();
      setRules(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取降噪规则失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  const validationError = useMemo(() => validateMuteRuleValue(inputType, inputValue), [inputType, inputValue]);
  const canAdd = !validationError && !adding && canAddMoreOfType(rules, inputType);

  const handleAdd = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canAdd) return;
    setAdding(true);
    setError(null);
    setNotice(null);
    try {
      const created = await muteRulesApi.create({ rule_type: inputType, value: inputValue.trim() });
      setNotice(`已添加${MUTE_RULE_TYPE_LABELS[created.rule_type]}规则「${created.value}」，相关内容已从你的列表中隐藏。`);
      setInputValue('');
      // 局部更新而非整表刷新：避免添加成功后列表闪回「加载中…」。
      // 后端列表按 created_at 新→旧返回，新规则直接置顶即可。
      setRules((prev) => [created, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加规则失败');
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (rule: MuteRuleItem) => {
    if (deletingId || !confirm(`确定删除${MUTE_RULE_TYPE_LABELS[rule.rule_type]}规则「${rule.value}」？删除后相关内容会重新出现在列表与精选中。`)) {
      return;
    }
    setDeletingId(rule.id);
    setError(null);
    setNotice(null);
    try {
      await muteRulesApi.remove(rule.id);
      setNotice(`已删除规则「${rule.value}」。`);
      // 同上：局部移除，不触发整表 loading
      setRules((prev) => prev.filter((item) => item.id !== rule.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除规则失败');
    } finally {
      setDeletingId(null);
    }
  };

  const grouped = useMemo(() => groupMuteRules(rules), [rules]);

  return (
    <Panel className="p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <VolumeX size={16} className="text-primary" />
          <h2 className="text-sm font-black text-gray-900">降噪规则</h2>
        </div>
        <Badge tone={rules.length > 0 ? 'teal' : 'neutral'}>
          {rules.length > 0 ? `${rules.length} 条规则` : '未添加'}
        </Badge>
      </div>
      <p className="mb-3 text-xs leading-5 text-gray-500">
        按关键词、信源或域名静音内容：命中项只从你自己的内容列表与今日精选中隐藏，不影响其他用户，也不会删除原始数据。
      </p>

      {error && (
        <div className="mb-3 rounded-sm border border-red-light bg-red-light px-3 py-2 text-xs font-bold text-red">{error}</div>
      )}
      {notice && (
        <div className="mb-3 rounded-sm border border-teal-border bg-teal-light px-3 py-2 text-xs font-bold text-teal">{notice}</div>
      )}

      {/* 添加规则 */}
      <form onSubmit={handleAdd} className="mb-4 grid gap-2 sm:grid-cols-[132px_1fr_auto] sm:items-end">
        <div>
          <FieldLabel htmlFor="mute-rule-type">规则类型</FieldLabel>
          <Select
            id="mute-rule-type"
            value={inputType}
            onChange={(event) => setInputType(event.target.value as MuteRuleType)}
          >
            {MUTE_RULE_TYPES.map((type) => (
              <option key={type} value={type}>
                {MUTE_RULE_TYPE_LABELS[type]}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <FieldLabel htmlFor="mute-rule-value" required>
            规则内容
          </FieldLabel>
          <TextInput
            id="mute-rule-value"
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            placeholder={inputType === 'source' ? '信源 ID（数字）' : inputType === 'domain' ? 'example.com' : '要屏蔽的关键词'}
            maxLength={255}
          />
          <p className="mt-1 text-[11px] leading-4 text-gray-400">{MUTE_RULE_TYPE_HINTS[inputType]}</p>
        </div>
        <Button type="submit" variant="primary" disabled={!canAdd} className="sm:mb-5">
          {adding ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          添加
        </Button>
      </form>

      {/* 三类分组列表 */}
      {loading ? (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Loader2 size={13} className="animate-spin" /> 加载中…
        </div>
      ) : (
        <div className="space-y-3">
          {MUTE_RULE_TYPES.map((type) => {
            const items = grouped[type];
            return (
              <div key={type} className="rounded-sm border border-gray-200 bg-gray-50 px-3 py-2.5">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 text-[11px] font-black text-gray-500">
                    <Badge tone={TYPE_BADGE_TONE[type]}>{MUTE_RULE_TYPE_LABELS[type]}</Badge>
                    <span>{items.length} 条</span>
                  </div>
                  {!canAddMoreOfType(rules, type) && (
                    <span className="text-[11px] font-bold text-amber">已达每类 50 条上限</span>
                  )}
                </div>
                {items.length === 0 ? (
                  <p className="text-[11px] leading-5 text-gray-400">暂无{MUTE_RULE_TYPE_LABELS[type]}规则。</p>
                ) : (
                  <ul className="space-y-1.5">
                    {items.map((rule) => (
                      <li
                        key={rule.id}
                        className="flex items-center gap-2 rounded-sm border border-gray-200 bg-white px-2.5 py-1.5"
                      >
                        <code className={cx('min-w-0 flex-1 truncate font-mono text-xs font-bold text-gray-800')}>
                          {rule.value}
                        </code>
                        <span className="shrink-0 text-[11px] text-gray-400">
                          {rule.created_at ? formatDateTime(rule.created_at, true) : ''}
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          className="shrink-0 min-h-8 px-2 py-1"
                          disabled={deletingId === rule.id}
                          onClick={() => handleDelete(rule)}
                          aria-label={`删除${MUTE_RULE_TYPE_LABELS[rule.rule_type]}规则 ${rule.value}`}
                        >
                          {deletingId === rule.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
