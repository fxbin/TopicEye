'use client';

import React, { useState } from 'react';
import { BookOpen, Compass, FileText, PenLine, Video } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import SectionTitle from '@/components/SectionTitle';
import { Button, Panel, Toolbar, cx } from '@/components/ui';
import CreationPlanDisplay, { type CreationPlan } from '@/components/CreationPlanDisplay';
import ExploreModeDialog from '@/components/ExploreModeDialog';

interface TopicCreationGeneratorProps {
  contentId: number;
}

export default function TopicCreationGenerator({ contentId }: TopicCreationGeneratorProps) {
  const { currentUser } = useAppContext();
  const [creationPlan, setCreationPlan] = useState<CreationPlan | null>(null);
  const [creating, setCreating] = useState(false);
  const [creatingPlatform, setCreatingPlatform] = useState<string | null>(null);
  const [creationError, setCreationError] = useState<string | null>(null);
  const [showExplore, setShowExplore] = useState(false);

  const platforms: Array<{ id: string; name: string; icon: LucideIcon }> = [
    { id: 'xiaohongshu', name: '小红书', icon: BookOpen },
    { id: 'wechat', name: '公众号', icon: FileText },
    { id: 'short_video', name: '短视频', icon: Video },
  ];

  const handleGeneratePlan = async (platform: string) => {
    if (!contentId) return;
    setCreating(true);
    setCreatingPlatform(platform);
    setCreationError(null);

    try {
      const { creationApi } = await import('@/lib/api');
      const result = await creationApi.generatePlan(contentId, platform) as CreationPlan & { _meta?: { platform: string } };
      setCreationPlan(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '生成失败';
      setCreationError(msg);
    } finally {
      setCreating(false);
      setCreatingPlatform(null);
    }
  };

  if (!currentUser) return null;

  return (
    <Panel className="mb-5 p-7">
      <SectionTitle>
        <span className="inline-flex items-center gap-2">
          <PenLine size={15} strokeWidth={2} />
          生成创作方案
        </span>
      </SectionTitle>
      <p className="mb-4 text-[13px] text-gray-500">
        选择平台快速生成方案，或用探索模式先找到差异化角度
      </p>

      {/* Explore mode entry */}
      <Toolbar className="mb-2.5 gap-2.5">
        <Button
          type="button"
          onClick={() => setShowExplore(true)}
          variant="secondary"
          className="px-[18px] py-2.5 text-[13px] font-medium"
        >
          <Compass size={14} strokeWidth={2} />
          探索模式
        </Button>
      </Toolbar>

      {/* Fast mode: platform buttons */}
      <Toolbar className="gap-2.5">
        {platforms.map((p) => {
          const Icon = p.icon;
          const active = creatingPlatform === p.id;
          return (
            <Button
              key={p.id}
              type="button"
              onClick={() => handleGeneratePlan(p.id)}
              disabled={creating}
              variant={active ? 'primary' : 'secondary'}
              className={cx('px-[18px] py-2.5 text-[13px] font-medium', creating && !active && 'opacity-50')}
            >
              <Icon size={14} strokeWidth={2} />
              {active ? '生成中...' : p.name}
            </Button>
          );
        })}
      </Toolbar>

      {/* Creation error */}
      {creationError && (
        <div className="mt-3 rounded-sm bg-red-light px-3.5 py-2.5 text-[13px] text-red">
          生成失败：{creationError}
        </div>
      )}

      {/* Creation plan result */}
      {creationPlan && (
        <Panel className="mt-4 bg-gray-50 p-5">
          <div className="mb-3 text-sm font-semibold text-gray-800">
            创作方案
          </div>
          <CreationPlanDisplay plan={creationPlan} platform={creationPlan._meta?.platform ?? creatingPlatform ?? ''} />
        </Panel>
      )}

      {/* Explore mode dialog */}
      {showExplore && (
        <ExploreModeDialog contentId={contentId} onClose={() => setShowExplore(false)} />
      )}
    </Panel>
  );
}
