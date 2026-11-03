import React from 'react';

/** 缺少可用原文地址时保留文字，不用 # 制造一次无意义跳转。 */
export default function SourceLink({ href, children, ...props }: Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { href?: string | null }) {
  let available = false;
  try {
    available = Boolean(href && ['http:', 'https:'].includes(new URL(href).protocol));
  } catch {
    // 没有完整原文地址时，仅展示标题。
  }
  if (available) return <a {...props} href={href!}>{children}</a>;
  return <span className={props.className} style={props.style} title="暂无原文链接">{children}</span>;
}
