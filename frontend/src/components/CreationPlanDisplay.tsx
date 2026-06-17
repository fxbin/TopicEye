'use client';

import React, { useState } from 'react';
import { Check, Clipboard, MessageSquare, MousePointer2, Music2, Paperclip, Pin, Video } from 'lucide-react';
import { formatPlanText } from '@/lib/utils';
import { Badge, Button, cx } from '@/components/ui';

interface Scene {
  seq: number;
  seconds: number;
  visual: string;
  narration: string;
}

interface OutlineSection {
  section: number;
  heading: string;
  points?: string[];
  evidence?: string;
}

export interface CreationPlan {
  titles?: string[];
  tone?: string;
  cover_slogan?: string;
  structure?: { hook?: string; points?: string[]; cta?: string };
  tags?: string[];
  hook?: string;
  scenes?: Scene[];
  total_seconds?: number;
  bgm_suggestion?: string;
  outline?: OutlineSection[];
  word_count_estimate?: number;
  key_quote?: string;
  closing?: string;
  _meta?: { platform: string; platform_name: string; content_id: number };
  [key: string]: unknown;
}

interface CreationPlanDisplayProps {
  plan: CreationPlan;
  platform: string;
}

export default function CreationPlanDisplay({ plan, platform }: CreationPlanDisplayProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    const text = formatPlanText(plan as Record<string, unknown>);
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Toolbar: 平台标签 + 导出 Markdown */}
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-gray-500">平台：{platform || '未知'}</span>
        <Button
          type="button"
          variant="secondary"
          onClick={() => exportPlanAsMarkdown(plan as Record<string, any>, platform)}
          className="!px-2 !py-1 text-[12px]"
        >
          <Download size={12} />
          导出 Markdown
        </Button>
      </div>
      {/* Copy button */}
      <div className="flex justify-end">
        <Button
          type="button"
          onClick={handleCopy}
          variant={copied ? 'success' : 'secondary'}
          className="min-h-0 px-3 py-1 text-[11px] font-semibold"
        >
          {copied ? <Check size={12} strokeWidth={2.4} /> : <Clipboard size={12} strokeWidth={2.2} />}
          {copied ? '已复制' : '复制全文'}
        </Button>
      </div>

      {/* Titles */}
      {plan.titles && plan.titles.length > 0 && (
        <div>
          <BlockLabel>备选标题</BlockLabel>
          {plan.titles.map((t: string, i: number) => (
            <div key={i} className={cx('mb-1 rounded-xs border-l-[3px] px-3 py-2 text-sm font-semibold leading-6 text-gray-900', i === 0 ? 'border-primary bg-primary-light/50' : 'border-transparent bg-gray-50')}>
              {t}
            </div>
          ))}
        </div>
      )}

      {/* Platform-specific: xiaohongshu */}
      {platform === 'xiaohongshu' && plan.structure && (
        <>
          {plan.cover_slogan && (
            <div className="rounded-xs border-l-[3px] border-primary bg-primary-light/60 px-3 py-2">
              <span className="text-[11px] font-semibold text-primary">封面文案：</span>
              <span className="text-[13px] text-gray-700"> {plan.cover_slogan}</span>
            </div>
          )}
          <div>
            <BlockLabel>正文结构</BlockLabel>
            {plan.structure.hook && (
              <div className="mb-1.5 flex gap-2 border-l-2 border-primary pl-3 text-[13px] leading-6 text-gray-700">
                <MousePointer2 size={14} className="mt-1 shrink-0 text-primary" strokeWidth={2} />
                <span><b>Hook:</b> {plan.structure.hook}</span>
              </div>
            )}
            {plan.structure.points?.map((p: string, i: number) => (
              <div key={i} className="mb-1 border-l-2 border-teal pl-3 text-[13px] leading-6 text-gray-700">
                {p}
              </div>
            ))}
            {plan.structure.cta && (
              <div className="flex gap-2 border-l-2 border-amber pl-3 text-[13px] leading-6 text-gray-700">
                <MessageSquare size={14} className="mt-1 shrink-0 text-amber" strokeWidth={2} />
                <span><b>互动引导:</b> {plan.structure.cta}</span>
              </div>
            )}
          </div>
          {plan.tags && plan.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {plan.tags.map((tag: string) => (
                <Badge key={tag} tone="primary" className="rounded-full px-2.5 py-0.5 text-[11px]">#{tag}</Badge>
              ))}
            </div>
          )}
        </>
      )}

      {/* Platform-specific: short_video */}
      {platform === 'short_video' && plan.scenes && (
        <>
          {plan.hook && (
            <div className="rounded-xs border-l-[3px] border-red bg-red-light px-3.5 py-2.5">
              <span className="text-[11px] font-semibold text-red">前3秒Hook：</span>
              <span className="text-[13px] text-gray-700"> {plan.hook}</span>
            </div>
          )}
          <div>
            <BlockLabel>分镜头脚本（共{plan.total_seconds || 60}秒）</BlockLabel>
            {plan.scenes.map((scene: Scene, i: number) => (
              <div key={i} className="mb-1.5 rounded-xs border-l-[3px] border-primary bg-gray-50 px-3.5 py-2.5">
                <div className="mb-1 flex justify-between">
                  <span className="text-xs font-bold text-primary">镜头 {scene.seq}</span>
                  <span className="text-[11px] text-gray-400">{scene.seconds}s</span>
                </div>
                <div className="mb-0.5 flex items-center gap-1.5 text-xs text-gray-500">
                  <Video size={13} strokeWidth={2} />
                  {scene.visual}
                </div>
                <div className="text-[13px] text-gray-700">{scene.narration}</div>
              </div>
            ))}
          </div>
          {plan.bgm_suggestion && (
            <div className="flex items-center gap-2 rounded-xs bg-gray-50 px-3 py-2 text-xs text-gray-500">
              <Music2 size={13} strokeWidth={2} />
              BGM建议：{plan.bgm_suggestion}
            </div>
          )}
        </>
      )}

      {/* Platform-specific: wechat */}
      {platform === 'wechat' && plan.outline && (
        <>
          <div>
            <BlockLabel>文章大纲（约{plan.word_count_estimate || 2000}字）</BlockLabel>
            {plan.outline.map((section: OutlineSection, i: number) => (
              <div key={i} className={cx('mb-1.5 rounded-xs border-l-[3px] bg-gray-50 px-3.5 py-3', i === 0 ? 'border-primary' : 'border-primary-border')}>
                <div className="mb-1 text-[13px] font-semibold text-gray-900">
                  {section.section}. {section.heading}
                </div>
                {section.points?.map((p: string, j: number) => (
                  <div key={j} className="pl-2 text-xs leading-6 text-gray-600">• {p}</div>
                ))}
                {section.evidence && (
                  <div className="mt-1 flex items-center gap-1 text-[11px] italic text-gray-400">
                    <Paperclip size={12} strokeWidth={2} />
                    {section.evidence}
                  </div>
                )}
              </div>
            ))}
          </div>
          {plan.key_quote && (
            <div className="rounded-xs border-l-[3px] border-primary bg-primary-light/50 px-4 py-3">
              <div className="mb-1 text-[11px] font-semibold text-primary">金句</div>
              <div className="text-sm font-semibold italic text-gray-900">「{plan.key_quote}」</div>
            </div>
          )}
          {plan.closing && (
            <div className="flex items-center gap-2 rounded-xs bg-gray-50 px-3.5 py-2.5 text-[13px] text-gray-600">
              <Pin size={13} strokeWidth={2} />
              结尾：{plan.closing}
            </div>
          )}
        </>
      )}

      {plan.tone && (
        <div className="text-center text-[11px] text-gray-400">风格建议：{plan.tone}</div>
      )}
    </div>
  );
}

function BlockLabel({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-gray-500">{children}</div>;
}
