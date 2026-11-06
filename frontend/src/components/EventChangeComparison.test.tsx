import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { EvidenceReaderLink } from './EventChangeComparison';

const openReader = vi.hoisted(() => vi.fn());
vi.mock('@/providers/ReaderProvider', () => ({ useReaderContext: () => ({ openReader }) }));

describe('依据阅读保留对照上下文', () => {
  it('普通点击打开现有抽屉，不离开对照页面', () => {
    openReader.mockClear();
    const link = EvidenceReaderLink({ id: 42, children: '依据报道' });
    const event = { defaultPrevented: false, button: 0, preventDefault: vi.fn() };
    link.props.onClick(event);
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(openReader).toHaveBeenCalledWith(42);
    expect(link.props.href).toBe('/contents/42/reader');
  });
  it.each(['metaKey', 'ctrlKey', 'shiftKey', 'altKey'])('保留%s修饰点击的浏览器行为', key => {
    openReader.mockClear();
    const link = EvidenceReaderLink({ id: 42, children: '依据报道' });
    const event = { defaultPrevented: false, button: 0, [key]: true, preventDefault: vi.fn() };
    link.props.onClick(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(openReader).not.toHaveBeenCalled();
  });
});
