'use client';

import React, { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, ShieldCheck } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import AdminSidebar from '@/components/AdminSidebar';
import AdminTopBar from '@/components/AdminTopBar';
import { Panel } from '@/components/ui';
import { AdminToaster } from '@/components/admin';

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { currentUser, authLoading } = useAppContext();
  const router = useRouter();

  // 未登录跳转放 effect：渲染期调 router.replace 会触发
  // 「Cannot update a component (Router) while rendering」（React 19 报错），
  // 渲染期只出占位
  useEffect(() => {
    if (!authLoading && !currentUser) {
      router.replace('/login');
    }
  }, [authLoading, currentUser, router]);

  // 加载中：显示骨架
  if (authLoading) {
    return (
      <div className="flex h-dvh items-center justify-center bg-page">
        <div className="inline-flex items-center gap-2 text-sm font-bold text-gray-500">
          <Loader2 size={16} className="animate-spin" />
          正在加载管理后台
        </div>
      </div>
    );
  }

  // 未登录：渲染跳转占位（跳转动作见上方 effect）
  if (!currentUser) {
    return (
      <div className="flex h-dvh items-center justify-center bg-page">
        <div className="inline-flex items-center gap-2 text-sm font-bold text-gray-500">
          <Loader2 size={16} className="animate-spin" />
          跳转登录...
        </div>
      </div>
    );
  }

  // 非管理员：显示权限提示（Phase 4 替换为专属 403 页）
  if (currentUser.role !== 'admin') {
    return (
      <div className="flex h-dvh items-center justify-center bg-page p-6">
        <Panel className="max-w-md p-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary-light">
            <ShieldCheck size={24} className="text-primary" strokeWidth={2} />
          </div>
          <h2 className="mb-2 text-base font-bold text-gray-900">需要管理员权限</h2>
          <p className="mb-5 text-[13px] leading-6 text-gray-500">
            当前页面仅对管理员开放。如果你的账号需要管理权限，请联系系统管理员开通。
          </p>
          <button
            type="button"
            onClick={() => router.replace('/')}
            className="rounded-sm border border-primary bg-primary px-4 py-2 text-sm font-bold text-white transition hover:bg-primary-hover"
          >
            返回首页
          </button>
        </Panel>
      </div>
    );
  }

  // 管理员：渲染 admin 专属壳
  return (
    <div className="flex h-dvh overflow-hidden">
      <AdminSidebar />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-page">
        <AdminTopBar />
        <div className="min-h-0 flex-1 overflow-auto">
          {children}
        </div>
      </main>
      {/* 操作反馈 Toast：系统级消息仍走 AdminNoticeBanner（#121 边界） */}
      <AdminToaster />
    </div>
  );
}
