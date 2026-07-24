'use client';

import React from 'react';
import { cx } from '@/components/ui';
import { FieldLabel } from '@/components/form';
import { sourcesApi } from '@/lib/api';

export interface FormState {
  name: string;
  source_type: string;
  url: string;
  keyword: string;
  category: string;
  weight: number;
  fetch_interval_minutes: number;
  enabled: boolean;
}

export const emptyForm: FormState = {
  name: '',
  source_type: 'RSS',
  url: '',
  keyword: '',
  category: 'AI',
  weight: 3,
  fetch_interval_minutes: 60,
  enabled: true,
};

// 注：此处 CATEGORIES 不含「全部」（8 项），与 @/lib/design-tokens.CATEGORIES（9 项含「全部」）有差异。
// 原因：信源表单是创建/编辑场景，不需要「全部」选项；design-tokens 版用于筛选/展示场景。
// 若后续信源也需要「全部」过滤，应改 import design-tokens 版。
// 注：此处 CATEGORIES 不含「全部」（8 项），与 @/lib/design-tokens.CATEGORIES（9 项含「全部」）有差异。
// 原因：信源表单是创建/编辑场景，不需要「全部」选项；design-tokens 版用于筛选/展示场景。
// 若后续信源也需要「全部」过滤，应改 import design-tokens 版。
export const CATEGORIES = ['AI', '商业', '科技', '教育', '自媒体', '生活', '职场', '产品'];
// 对齐后端 SourceType 枚举 + 已注册的 scraper（见 backend/app/services/scrapers/__init__.py）
export const SOURCE_TYPES = [
  'RSS', 'RSSHub', 'Reddit', 'API', '网站',
  'YouTube', 'Podcast', 'Newsletter', 'X', 'TwitterRSS', 'Zhihu',
];
export const SOURCE_INTERVAL_OPTIONS = [
  { value: 30, label: '30分钟' },
  { value: 60, label: '1小时' },
  { value: 120, label: '2小时' },
  { value: 360, label: '6小时' },
  { value: 720, label: '12小时' },
  { value: 1440, label: '1天' },
];

interface SourceFormProps {
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
}

const inputClass = 'h-9 w-full rounded-xs border border-gray-200 bg-white px-3 text-sm text-gray-800 outline-none transition placeholder:text-gray-300 focus:border-primary-border focus:ring-2 focus:ring-primary-light';

// ─── Per-type URL placeholder + hint ────────────────────────────────────
const URL_PLACEHOLDERS: Record<string, string> = {
  RSS: 'https://example.com/feed',
  RSSHub: 'xiaohongshu/user/profile/xxx',
  Reddit: 'https://www.reddit.com/r/ai/hot/.rss',
  API: 'https://example.com/api/items',
  '网站': 'https://example.com',
  YouTube: 'https://www.youtube.com/@handle',
  Podcast: 'https://xxx.substack.com',
  Newsletter: 'https://xxx.substack.com',
  X: 'https://x.com/search',
  TwitterRSS: 'https://xgo.ing/username/rss',
};

const TYPE_HINTS: Record<string, string> = {
  TwitterRSS: '通过 xgo.ing 将 X 用户时间线转为 RSS。格式：https://xgo.ing/{用户名}/rss。粘贴 URL 后自动识别类型。',
  X: '通过 Apify 直连 X API，需配置环境变量 APIFY_TOKEN。下方配置填写搜索关键词或 JSON 格式的用户列表。',
  RSSHub: '填写 RSSHub 路由（不含域名），如 weibo/user/123 或 bilibili/user/456。系统自动尝试多个 RSSHub 实例。',
};

// ─── Per-type keyword/config field ─────────────────────────────────────
type KeywordFieldConfig = {
  show: boolean;
  label: string;
  hint?: string;
  placeholder: string;
  isJson?: boolean;
};

function getKeywordFieldConfig(sourceType: string): KeywordFieldConfig {
  switch (sourceType) {
    case 'API':
      return {
        show: true,
        label: 'API 配置',
        hint: 'JSON 格式，可选',
        placeholder: '{"items_path":"data.items","fields":{"title":"title","url":"url","summary":"summary"}}',
        isJson: true,
      };
    case 'TwitterRSS':
      return {
        show: true,
        label: '高级配置',
        hint: 'JSON 格式，可选（留空使用默认）',
        placeholder: '{"fetch_limit":50,"include_retweets":false,"api_key":"可选"}',
        isJson: true,
      };
    case 'X':
      return {
        show: true,
        label: '搜索关键词 / 用户列表',
        hint: '直接填搜索词（如 AI agents），或 JSON 格式配置',
        placeholder: 'AI agents\n或\n{"users":["elonmusk","openai"],"fetch_limit":50}',
      };
    default:
      return { show: false, label: '', placeholder: '' };
  }
}

export default function SourceForm({ form, setForm }: SourceFormProps) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <FieldLabel required>信源名称</FieldLabel>
        <input
          type="text"
          placeholder="例：量子位"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          className={inputClass}
        />
      </div>

      <div>
        <FieldLabel>类型</FieldLabel>
        <select
          value={form.source_type}
          onChange={(e) => setForm((f) => ({ ...f, source_type: e.target.value }))}
          className={inputClass}
        >
          {SOURCE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      <div>
        <FieldLabel>URL / 地址</FieldLabel>
        <input
          type="text"
          placeholder={URL_PLACEHOLDERS[form.source_type] || 'https://example.com/feed'}
          value={form.url}
          onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
          onBlur={async (e) => {
            const pastedUrl = e.target.value.trim();
            if (!pastedUrl) return;
            try {
              const result = await sourcesApi.recognizeMine(pastedUrl, form.name || undefined);
              // 用识别结果覆盖（仅当当前类型是默认 RSS 或与识别结果不同时）
              setForm((f) => ({
                ...f,
                source_type: SOURCE_TYPES.includes(result.source_type) ? result.source_type : f.source_type,
                url: result.normalized_url || f.url,
              }));
            } catch {
              // 识别失败静默处理，用户可手动选类型
            }
          }}
          className={cx(inputClass, 'font-mono')}
        />
        {TYPE_HINTS[form.source_type] ? (
          <p className="mt-1 text-[11px] leading-4 text-gray-400">{TYPE_HINTS[form.source_type]}</p>
        ) : (
          <p className="mt-1 text-[11px] text-gray-400">粘贴 URL 后自动识别类型（失焦触发）</p>
        )}
      </div>

      {(() => {
        const kwConfig = getKeywordFieldConfig(form.source_type);
        if (!kwConfig.show) return null;
        return (
          <div>
            <FieldLabel>
              {kwConfig.label}
              {kwConfig.hint && (
                <span className="ml-2 text-[11px] font-normal text-gray-400">{kwConfig.hint}</span>
              )}
            </FieldLabel>
            <textarea
              value={form.keyword}
              onChange={(e) => setForm((f) => ({ ...f, keyword: e.target.value }))}
              placeholder={kwConfig.placeholder}
              className="min-h-28 w-full resize-y rounded-xs border border-gray-200 bg-white px-3 py-2 font-mono text-xs leading-5 text-gray-800 outline-none transition placeholder:text-gray-300 focus:border-primary-border focus:ring-2 focus:ring-primary-light"
            />
          </div>
        );
      })()}

      <div>
        <FieldLabel>分类</FieldLabel>
        <select
          value={form.category}
          onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
          className={inputClass}
        >
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      <div>
        <FieldLabel>
          信源权重
          <span className="ml-2 text-[11px] font-normal text-gray-400">权重越高，精选评分加分越多</span>
        </FieldLabel>
        <div className="flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setForm((f) => ({ ...f, weight: w }))}
              className={cx('text-lg leading-none transition', w <= form.weight ? 'text-primary' : 'text-gray-200')}
            >
              ●
            </button>
          ))}
          <span className="ml-2 font-mono text-xs text-gray-500">
            {form.weight}/5 {form.weight > 3 ? `(+${(form.weight - 3) * 6}分)` : form.weight < 3 ? `(${(form.weight - 3) * 6}分)` : '(基准)'}
          </span>
        </div>
      </div>

      <div>
        <FieldLabel>采集频率</FieldLabel>
        <div className="grid grid-cols-3 gap-1.5">
          {SOURCE_INTERVAL_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setForm((f) => ({ ...f, fetch_interval_minutes: opt.value }))}
              className={cx(
                'h-8 rounded-xs border px-2 text-xs transition',
                form.fetch_interval_minutes === opt.value
                  ? 'border-primary-border bg-primary-light font-bold text-primary'
                  : 'border-gray-200 bg-white font-medium text-gray-600 hover:border-gray-300',
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
          className="h-4 w-4 cursor-pointer accent-primary"
          id="src-enabled"
        />
        <label htmlFor="src-enabled" className="cursor-pointer text-[13px] font-bold text-gray-700">启用此信源</label>
      </div>
    </div>
  );
}
