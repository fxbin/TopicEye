'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { AlertCircle } from 'lucide-react';
import { Button, Panel } from '@/components/ui';

export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error('页面渲染失败', error); }, [error]);
  return (
    <div data-page-error className="flex min-h-full items-center justify-center px-4 py-8">
      <Panel className="w-full max-w-md p-6">
        <AlertCircle className="mb-4 text-red" size={28} aria-hidden="true" />
        <h1 className="text-xl font-bold text-gray-900">页面暂时无法加载</h1>
        <p role="alert" className="mt-3 text-sm leading-7 text-gray-600">请重试加载当前页面。若问题持续，可以先返回首页使用其他功能。</p>
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <Button onClick={reset} variant="primary">重试加载</Button>
          <Link href="/" className="text-sm font-medium text-primary-text underline underline-offset-4">返回首页</Link>
        </div>
      </Panel>
    </div>
  );
}
