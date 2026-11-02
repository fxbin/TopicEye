'use client';

import { useEffect, useState } from 'react';
import { Gauge } from 'lucide-react';
import { AdminPageHeader, AdminPageShell } from '@/components/admin-ui';
import { Panel, Button } from '@/components/ui';
import { ErrorState, LoadingState } from '@/components/StateView';

export default function MonitoringDashboardPage() {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    if (state !== 'loading') return;
    const timer = setTimeout(() => setState('error'), 15000);
    return () => clearTimeout(timer);
  }, [state, attempt]);

  const retry = () => { setState('loading'); setAttempt(value => value + 1); };
  return (
    <AdminPageShell className="flex h-full min-h-0 flex-col">
      <AdminPageHeader
        title="监控大盘"
        icon={Gauge}
        description="查看系统体检、运行日志与前端体验。"
        actions={<Button onClick={retry} disabled={state === 'loading'}>重新加载</Button>}
      />
      <Panel className="relative min-h-0 flex-1 overflow-hidden">
        {state === 'loading' && <div className="absolute inset-0 z-10 bg-white"><LoadingState label="正在加载监控大盘…" minHeight="240px" /></div>}
        {state === 'error' && <ErrorState error="监控大盘未能加载，请检查登录状态或重试。" onRetry={retry} panel={false} />}
        {state !== 'error' && (
          <iframe
            key={attempt}
            src="/api/v1/metrics/dashboard"
            title="系统监控画布"
            className="h-full w-full border-0"
            onLoad={event => {
              try {
                const ready = event.currentTarget.contentDocument?.querySelector('[data-dashboard="embedded"]');
                setState(ready ? 'ready' : 'error');
              } catch { setState('error'); }
            }}
            onError={() => setState('error')}
          />
        )}
      </Panel>
    </AdminPageShell>
  );
}
