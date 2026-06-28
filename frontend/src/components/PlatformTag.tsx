'use client';

import React from 'react';
import { PLATFORM_COLOR_MAP } from '@/lib/design-tokens';

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
