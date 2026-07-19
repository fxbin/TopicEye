'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, ShieldCheck } from 'lucide-react';
import { useAppContext } from '@/components/ClientLayout';
import AdminSidebar from '@/components/AdminSidebar';
import AdminTopBar from '@/components/AdminTopBar';
import { Panel } from '@/components/ui';

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { currentUser, authLoading } = useAppContext();
  const router = useRouter();

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

  // 未登录：跳转登录页
  if (!currentUser) {
    if (typeof window !== 'undefined') {
      router.replace('/login');
    }
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
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-50">
            <ShieldCheck size={24} className="text-amber-500" strokeWidth={2} />
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
    </div>
  );
}
