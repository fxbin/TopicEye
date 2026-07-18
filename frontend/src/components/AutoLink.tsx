import React from 'react';

const URL_RE = /(https?:\/\/[^\s<>"'，。、；）】]+)/g;

/**
 * 把文本里的裸 URL 渲染成可点击链接，其余文本原样输出。
 * 纯 React 组件，不走 dangerouslySetInnerHTML，无 XSS 风险。
 *
 * 用法：<AutoLink text={pick.reason} className="text-primary hover:underline" />
 */
export function AutoLink({ text, className }: { text?: string | null; className?: string }) {
  if (!text) return null;
  // split 带捕获组：奇数下标为 URL，偶数下标为普通文本
  const parts = text.split(URL_RE);
  if (parts.length === 1) {
    return <>{text}</>;
  }
  return (
    <>
      {parts.map((part, i) => {
        if (i % 2 === 1) {
          // 奇数位 = URL（捕获组）
          return (
            <a
              key={i}
              href={part}
              target="_blank"
              rel="noopener noreferrer"
              className={className ?? 'font-medium text-blue-600 underline decoration-blue-300 underline-offset-2 hover:text-blue-700 hover:decoration-blue-500 break-all'}
            >
              {part}
            </a>
          );
        }
        return <React.Fragment key={i}>{part}</React.Fragment>;
      })}
    </>
  );
}
