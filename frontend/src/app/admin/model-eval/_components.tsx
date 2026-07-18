/**
 * Model eval page UI 原子组件。
 *
 * 历史：本文件曾本地定义 Surface / StatTile / StatusPill / FieldLabel /
 * TextInput / SelectInput / InfoCell 共 7 个原子。Phase B-B3 已将其中
 * 5 个收敛到公共组件层：
 * - Surface / StatTile → `@/components/ui` + `@/components/StatTile`
 * - FieldLabel / TextInput / Select（此处别名 SelectInput） → `@/components/form`
 *
 * 本文件保留页面专属的 2 个原子：
 * - StatusPill     状态徽章（Badge 包装，排除 purple tone）
 * - InfoCell       信息格子（label + value 组合，model-eval 专属布局）
 *
 * 调用方（UsageTab / EvaluateTab / ModelsTab / ModelEditForm / HistoryTab）
 * 继续从 `./_components` 导入，re-export 保持 import 路径不变。
 */

import React from 'react';
import { Badge, cx } from '@/components/ui';

// ─── 公共组件 re-export（保持调用方 import 路径不变） ────────────────

export { Surface } from '@/components/ui';
export { StatTile } from '@/components/StatTile';
export { FieldLabel, TextInput } from '@/components/form';
// 本地历史命名为 SelectInput，公共版命名为 Select；用别名保持兼容。
export { Select as SelectInput } from '@/components/form';

// ─── 页面专属原子 ────────────────────────────────────────────────────

import type { Tone } from './_model-eval-utils';

export function StatusPill({
  children,
  tone = 'neutral',
}: {
  children: React.ReactNode;
  tone?: Exclude<Tone, 'purple'>;
}) {
  const badgeTone = tone === 'neutral' ? 'neutral' : tone;
  return (
    <Badge tone={badgeTone} className="gap-1 whitespace-nowrap py-0.5">
      {children}
    </Badge>
  );
}

export function InfoCell({ label, value, muted = false }: { label: string; value: React.ReactNode; muted?: boolean }) {
  return (
    <div className="min-w-0 rounded-xs border border-gray-200 bg-gray-50 px-2.5 py-2">
      <div className="mb-1 truncate text-[10px] text-gray-400">{label}</div>
      <div className={cx('truncate font-mono text-xs font-black', muted ? 'text-gray-400' : 'text-gray-800')}>{value}</div>
    </div>
  );
}
