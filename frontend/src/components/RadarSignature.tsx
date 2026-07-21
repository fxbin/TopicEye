'use client';

import React from 'react';

/**
 * RadarSignature — TopicEye 品牌签名元素。
 *
 * 用极简同心圆 + 旋转扫描线表达「雷达 / 信号扫描」意象，
 * 呼应产品名「选题雷达」。纯 SVG + CSS 动画，无 JS 依赖，零布局抖动。
 *
 * 用法：
 *   <RadarSignature size={40} />            // 页头签名
 *   <RadarSignature size={24} active />     // 强调态
 */

export function RadarSignature({
  size = 40,
  className,
}: {
  size?: number;
  className?: string;
}) {
  const id = React.useId();
  const sweepId = `radar-sweep-${id}`;
  return (
    <span
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size,
        height: size,
        flexShrink: 0,
      }}
      aria-hidden="true"
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 48 48"
        fill="none"
        style={{ display: 'block', overflow: 'visible' }}
      >
        <defs>
          {/* 扫描线锥形渐变：从主色到透明，形成「扫过的余晖」 */}
          <linearGradient id={sweepId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#FF6B35" stopOpacity="0" />
            <stop offset="100%" stopColor="#FF6B35" stopOpacity="0.55" />
          </linearGradient>
        </defs>

        {/* 同心圆（雷达网格），由外到内渐淡 */}
        <circle cx="24" cy="24" r="21" stroke="#FFD0B5" strokeWidth="1.5" />
        <circle cx="24" cy="24" r="14" stroke="#FFD0B5" strokeWidth="1.2" opacity="0.7" />
        <circle cx="24" cy="24" r="7" stroke="#FFD0B5" strokeWidth="1" opacity="0.5" />

        {/* 旋转扫描扇面 + 扫描线 */}
        <g className="radar-signature-sweep" style={{ transformOrigin: '24px 24px' }}>
          <path d="M24 24 L24 3 A21 21 0 0 1 42.6 14.5 Z" fill={`url(#${sweepId})`} />
          <line x1="24" y1="24" x2="24" y2="3" stroke="#FF6B35" strokeWidth="1.8" strokeLinecap="round" />
        </g>

        {/* 中心信号点 + 脉冲扩散（复用全局 radar-ping） */}
        <circle cx="24" cy="24" r="3" fill="#FF6B35" />
        <circle
          cx="24"
          cy="24"
          r="3"
          fill="none"
          stroke="#FF6B35"
          strokeWidth="1.5"
          className="radar-signature-ping"
          style={{ transformOrigin: '24px 24px' }}
        />

        {/* 一个被「扫到」的目标点，闪烁提示发现感 */}
        <circle cx="33" cy="17" r="2" fill="#00C9A7" className="radar-signature-blip" />
      </svg>
    </span>
  );
}

export default RadarSignature;
