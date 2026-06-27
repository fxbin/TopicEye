'use client';

import React from 'react';

interface PlatformTagProps {
  name: string;
}

export default function PlatformTag({ name }: PlatformTagProps) {
  const c = PLATFORM_COLOR_MAP[name] || { bg: '#F3F4F6', color: '#4B5563' };

  return (
    <span
      className="inline-block rounded px-2 py-0.5 text-[11px] font-medium"
      style={{
        color: c.color,
        background: c.bg,
      }}
    >
      {name}
    </span>
  );
}

const PLATFORM_COLOR_MAP: Record<string, { bg: string; color: string }> = {
  公众号: { bg: '#EEF2FF', color: '#4F46E5' },
  小红书: { bg: '#FFF1F2', color: '#E11D48' },
  视频号: { bg: '#ECFDF5', color: '#059669' },
  知乎: { bg: '#EFF6FF', color: '#2563EB' },
  抖音: { bg: '#F5F3FF', color: '#7C3AED' },
  arXiv: { bg: '#FEF3C7', color: '#B45309' },
};
