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
      <div className="mb-1.5 flex items-baseline gap-3">
        <h1 className="text-[26px] font-bold text-gray-900">{title}</h1>
        {date && <span className="text-sm text-gray-500">{date}</span>}
      </div>
      {subtitle && (
        <p className="text-[13px] text-gray-500">{subtitle}</p>
      )}
      {stats && stats.length > 0 && (
        <div className="flex gap-4 text-[13px] text-gray-500">
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
