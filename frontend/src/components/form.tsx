'use client';

/**
 * 通用表单原语。
 *
 * 收敛此前散落在 4 处的重复定义：
 * - `app/feedback/page.tsx`        FieldLabel + TextInput + TextArea + Select
 * - `app/model-eval/_components.tsx` FieldLabel + TextInput + SelectInput（命名不一致）
 * - `app/mother-topics/config/page.tsx` FieldLabel（className 略不同）
 * - `components/SourceForm.tsx`     FieldLabel + inputClass 常量
 *
 * 规范：以 feedback 版样式为基准（最完整），统一命名与 className。
 * `FieldLabel` 新增 `required?: boolean`，用于渲染 `<span className="text-red">*</span>`。
 */

import React from 'react';
import { cx } from '@/components/ui';

// ─── FieldLabel ─────────────────────────────────────────────────────

export function FieldLabel({
  children,
  required = false,
  className,
  htmlFor,
}: {
  children: React.ReactNode;
  required?: boolean;
  className?: string;
  htmlFor?: string;
}) {
  return (
    <label htmlFor={htmlFor} className={cx('mb-1 block text-xs font-bold text-gray-500', className)}>
      {children}
      {required && <span className="text-red"> *</span>}
    </label>
  );
}

// ─── TextInput ──────────────────────────────────────────────────────

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        'h-9 w-full rounded-xs border border-gray-200 bg-white px-3 text-[13px] text-gray-800 outline-none transition placeholder:text-gray-300 focus:border-primary-border focus:ring-2 focus:ring-primary-light',
        props.className,
      )}
    />
  );
}

// ─── TextArea ───────────────────────────────────────────────────────

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cx(
        'min-h-[104px] w-full resize-y rounded-xs border border-gray-200 bg-white px-3 py-2 text-[13px] leading-6 text-gray-800 outline-none transition placeholder:text-gray-300 focus:border-primary-border focus:ring-2 focus:ring-primary-light',
        props.className,
      )}
    />
  );
}

// ─── Select ──────────────────────────────────────────────────────────

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx(
        'h-9 w-full rounded-xs border border-gray-200 bg-white px-3 text-[13px] font-bold text-gray-700 outline-none transition focus:border-primary-border focus:ring-2 focus:ring-primary-light',
        props.className,
      )}
    />
  );
}
