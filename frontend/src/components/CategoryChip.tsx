'use client';

import React from 'react';
import { cx } from '@/components/ui';

interface CategoryChipProps {
  name: string;
  active: boolean;
  onClick: () => void;
}

export default function CategoryChip({ name, active, onClick }: CategoryChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        'rounded-full border px-4 py-1.5 text-[13px] transition',
        active ? 'border-primary-solid bg-primary-solid font-semibold text-white' : 'border-gray-200 bg-white font-normal text-gray-600 hover:border-primary-border hover:text-primary-text',
      )}
    >
      {name}
    </button>
  );
}
