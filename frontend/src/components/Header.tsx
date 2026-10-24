'use client';

import React from 'react';

interface HeaderProps {
  title: string;
  subtitle?: string;
  date?: string;
  stats?: { label: string; value: number; color?: string }[];
}

export default function Header({ title, subtitle, date, stats }: HeaderProps) {
  return (
    <div className="mb-7 max-w-[820px]">
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-2xl font-bold leading-snug sm:text-[26px] text-gray-900">{title}</h1>
        {date && <span className="text-sm text-gray-500">{date}</span>}
      </div>
      {subtitle && (
        <p className="text-sm leading-relaxed text-gray-600">{subtitle}</p>
      )}
      {stats && stats.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm leading-relaxed text-gray-600">
          {stats.map((s, i) => (
            <span key={i}>
              {s.label}{' '}
              <b className="font-mono" style={{ color: s.color || 'var(--color-primary-text)' }}>{s.value}</b>{' '}
              条
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
