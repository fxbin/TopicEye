'use client';

import React from 'react';
import { Toaster, toast } from 'sonner';

/**
 * 后台 Toast（#121 圆桌规范）：
 * - 位置右上、距视口 16px、宽 min(360px, 100vw−32px)、圆角 8
 * - 边界：操作反馈（保存成功/复制完成）归 Toast；
 *   系统级需动作的消息（配额告警等）仍走 AdminNoticeBanner——
 *   Toast 转瞬即逝，恢复路径优先于视觉干净
 * - AdminToaster 在 admin layout 挂载一次；页面里 `import { toast } from '@/components/admin'`
 */
export function AdminToaster() {
  return (
    <Toaster
      position="top-right"
      offset={16}
      gap={8}
      toastOptions={{
        duration: 3200,
        style: {
          width: 'min(360px, calc(100vw - 32px))',
          borderRadius: '8px',
          border: '1px solid var(--color-ink-200)',
          color: 'var(--color-ink-900)',
          fontFamily: 'var(--font-sans)',
          fontSize: '13px',
        },
      }}
    />
  );
}

export { toast };
