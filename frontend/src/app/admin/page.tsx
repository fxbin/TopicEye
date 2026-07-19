'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import {
  BookOpen,
  BrainCircuit,
  LayoutDashboard,
  MessageSquareWarning,
  Newspaper,
  RadioTower,
  Rocket,
  Settings,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { Panel } from '@/components/ui';

interface AdminDashboardCard {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  description: string;
}

const DASHBOARD_CARDS: AdminDashboardCard[] = [
  { id: 'sources', label: '信源管理', href: '/admin/sources', icon: RadioTower, description: '管理系统公共信源、采集频率与同步状态' },
  { id: 'contents', label: '内容管理', href: '/admin/contents', icon: Newspaper, description: '查看与维护内容池、原文快照与增强状态' },
  { id: 'users', label: '用户管理', href: '/admin/users', icon: Users, description: '管理用户角色、套餐、封禁与密码重置' },
  { id: 'model-eval', label: 'AI 引擎', href: '/admin/model-eval', icon: BrainCircuit, description: '配置与评测 LLM 模型、查看用量与效果' },
  { id: 'mother-topics', label: '母题配置', href: '/admin/mother-topics', icon: BookOpen, description: '维护母题库与关键词映射规则' },
  { id: 'updates', label: '发版记录', href: '/admin/updates', icon: Rocket, description: '管理版本发布记录与路线图' },
  { id: 'feedback', label: '反馈工作台', href: '/admin/feedback', icon: MessageSquareWarning, description: '查看与处理用户反馈、追踪修复状态' },
  { id: 'settings', label: '系统设置', href: '/admin/settings', icon: Settings, description: '邮件服务、功能开关等全局配置' },
];

export default function AdminDashboardPage() {
  const router = useRouter();

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-8">
      {/* Header */}
      <header className="mb-6">
        <div className="flex items-center gap-2 text-[11px] font-bold tracking-[0.08em] text-amber-600">
          <LayoutDashboard size={14} strokeWidth={2.4} />
          ADMIN DASHBOARD
        </div>
        <h1 className="mt-2 text-[24px] font-black leading-tight text-gray-900">管理后台概览</h1>
        <p className="mt-1 text-[13px] text-gray-500">
          从这里进入各项管理功能。所有管理操作仅对管理员开放。
        </p>
      </header>

      {/* Cards grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {DASHBOARD_CARDS.map((card) => {
          const Icon = card.icon;
          return (
            <button
              key={card.id}
              type="button"
              onClick={() => router.push(card.href)}
              className="group text-left"
            >
              <Panel className="h-full p-4 transition hover:border-amber-300 hover:shadow-[0_4px_16px_rgba(217,119,6,0.08)]">
                <div className="mb-2.5 flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-sm bg-amber-50 text-amber-600 transition group-hover:bg-amber-100">
                    <Icon size={18} strokeWidth={2} />
                  </div>
                  <span className="text-[15px] font-bold text-gray-900">{card.label}</span>
                </div>
                <p className="text-[12px] leading-5 text-gray-500">
                  {card.description}
                </p>
              </Panel>
            </button>
          );
        })}
      </div>
    </div>
  );
}
