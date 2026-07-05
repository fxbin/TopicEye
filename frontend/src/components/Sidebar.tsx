'use client';

import React from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  LogIn,
  LogOut,
  Radar,
  UserRound,
} from 'lucide-react';
import { cx } from '@/components/ui';
import { isAdmin, visibleNavSpaces } from '@/lib/navigation';
import type { AuthUser } from '@/types';

interface SidebarProps {
  topicCount?: number;
  favCount?: number;
  sourceCount?: number;
  compact?: boolean;
  currentUser?: AuthUser | null;
  authLoading?: boolean;
  enabledFeatures?: Record<string, boolean>;
  onLogout?: () => void;
}

export default function Sidebar({
  topicCount = 0,
  favCount = 0,
  sourceCount = 0,
  compact = false,
  currentUser = null,
  authLoading = false,
  enabledFeatures,
  onLogout,
}: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();

  const navSpaces = visibleNavSpaces(currentUser, enabledFeatures);
  const counts = {
    topics: topicCount,
    favorites: favCount,
    sources: sourceCount,
  };

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  };

  return (
    <div
      className="relative flex h-screen shrink-0 select-none flex-col border-r border-gray-200 bg-white"
      style={{ width: compact ? 72 : 220 }}
    >
      {/* Brand */}
      <div className={compact ? 'px-3.5 pb-7 pt-6' : 'px-6 pb-8 pt-7'}>
        <div className={cx('flex items-center gap-2.5', compact ? 'justify-center' : 'justify-start')}>
          <div className="relative h-7 w-7">
            {/* Radar icon */}
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-primary to-[#FF8F65]">
              <Radar size={16} className="text-white" strokeWidth={2.4} />
            </div>
            {/* Ping */}
            <div className="absolute left-0 top-0 h-7 w-7 animate-radar-ping rounded-full border-2 border-primary" />
          </div>
          {!compact && <div>
            <div className="text-[17px] font-bold leading-tight text-gray-900">
              选题雷达
            </div>
            <div className="mt-px text-[10px] tracking-[0.08em] text-gray-400">
              TOPIC RADAR
            </div>
          </div>}
        </div>
      </div>

      {/* Navigation */}
      <nav className={cx('flex-1 overflow-y-auto', compact ? 'px-2.5' : 'px-3')}>
        {navSpaces.map((space) => (
          <div key={space.id} className={compact ? 'mb-3' : 'mb-4.5'}>
            {!compact && (
              <div className="px-3 pb-2 text-[11px] font-bold tracking-[0.08em] text-gray-400">
                {space.label}
              </div>
            )}
            {space.items.map((item) => {
              const active = isActive(item.href);
              const Icon = item.icon;
              const count = item.countKey ? counts[item.countKey] : 0;
              return (
                <button
                  key={item.id}
                  type="button"
                  title={compact ? item.label : undefined}
                  onClick={() => router.push(item.href)}
                  className={cx(
                    'mb-0.5 flex w-full items-center rounded-sm border-0 text-sm transition',
                    compact ? 'justify-center px-0 py-2.5' : 'justify-between px-3 py-2.5 text-left',
                    active ? 'bg-primary-light font-semibold text-primary' : 'bg-transparent font-normal text-gray-600 hover:bg-gray-50 hover:text-gray-900',
                  )}
                >
                  <span className="flex items-center gap-2">
                    <Icon size={16} strokeWidth={active ? 2.2 : 1.8} />
                    {!compact && <span>{item.label}</span>}
                  </span>
                  {!compact && count > 0 ? (
                    <span className={cx('rounded-full px-2 py-px font-mono text-[11px] font-medium', active ? 'bg-primary/10 text-primary' : 'bg-gray-100 text-gray-400')}>
                      {count}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Bottom User Area */}
      <div className={cx('border-t border-gray-100 pb-4 pt-3', compact ? 'px-2.5' : 'px-3')}>
        {currentUser ? (
          <div className={cx('flex items-center gap-2', compact ? 'justify-center p-0' : 'justify-between px-3')}>
            <div className="flex min-w-0 items-center gap-2">
              <button
                type="button"
                onClick={() => router.push('/profile')}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-teal to-[#7DD3C0] text-xs font-semibold text-white transition hover:opacity-90"
                title="个人中心"
              >
                <UserRound size={14} strokeWidth={2} />
              </button>
              {!compact && (
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium text-gray-700">{currentUser.display_name || currentUser.email}</div>
                  <div className="text-[10px] text-gray-400">
                    {isAdmin(currentUser) ? '管理员' : currentUser.plan === 'free' ? '免费版' : '付费版'}
                  </div>
                </div>
              )}
            </div>
            {!compact && (
              <button
                type="button"
                onClick={onLogout}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-gray-400 transition hover:bg-gray-100 hover:text-red"
                title="退出登录"
              >
                <LogOut size={14} strokeWidth={2} />
              </button>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => router.push('/login')}
            className={cx(
              'flex w-full items-center rounded-sm text-sm transition hover:bg-gray-50 hover:text-primary',
              compact ? 'justify-center px-0 py-2.5' : 'justify-start gap-2 px-3 py-2.5 text-left text-gray-600',
            )}
            title={compact ? '登录' : undefined}
            disabled={authLoading}
          >
            <LogIn size={16} strokeWidth={2} />
            {!compact && <span>{authLoading ? '检查登录' : '登录'}</span>}
          </button>
        )}
        {currentUser && !compact && (
          <button
            type="button"
            onClick={() => router.push('/profile')}
            className="mt-2 flex w-full items-center justify-start gap-2 rounded-sm px-3 py-2 text-left text-xs font-bold text-gray-500 transition hover:bg-gray-50 hover:text-primary"
          >
            <UserRound size={14} strokeWidth={2} />
            个人中心
          </button>
        )}
      </div>
    </div>
  );
}
