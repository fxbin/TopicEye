'use client';

import { cx } from '@/components/ui';

/**
 * 日报 / 周报 / 月报 三报切换 tab。
 * 在 daily/weekly/monthly 三个报告页顶部共用。
 *
 * 当前激活页由 `current` prop 指定，避免依赖 usePathname 引起的
 * 服务端/客户端不一致警告。SSG 友好。
 */
export default function DailyWeeklyMonthlyTabs({ current }: { current: 'daily' | 'weekly' | 'monthly' }) {
  const tabs: { key: typeof current; href: string; label: string }[] = [
    { key: 'daily', href: '/daily', label: '日报' },
    { key: 'weekly', href: '/weekly', label: '周报' },
    { key: 'monthly', href: '/monthly', label: '月报' },
  ];

  return (
    <div className="flex items-center gap-1 border-b border-gray-200 bg-white px-4 py-2">
      <div className="flex items-center gap-0.5">
        {tabs.map((tab) => {
          const active = tab.key === current;
          return (
            <a
              key={tab.key}
              href={tab.href}
              className={cx(
                'rounded px-3 py-1 text-xs font-black transition',
                active ? 'bg-primary-light text-primary' : 'font-bold text-gray-400 hover:text-gray-700',
              )}
            >
              {tab.label}
            </a>
          );
        })}
      </div>
    </div>
  );
}
