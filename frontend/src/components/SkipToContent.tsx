'use client';

import { useEffect, type MouseEvent } from 'react';

function getPrimaryMain(): HTMLElement | null {
  const main = document.querySelector('main');
  return main instanceof HTMLElement ? main : null;
}

/**
 * A global keyboard shortcut for bypassing repeated navigation. The client
 * shell owns the primary <main>, so it is identified at activation time to
 * keep the root layout server-rendered and avoid duplicating landmarks.
 */
export default function SkipToContent() {
  useEffect(() => {
    const main = getPrimaryMain();
    if (!main) return;

    main.id = 'main-content';
    main.tabIndex = -1;
  }, []);

  const skipToContent = (event: MouseEvent<HTMLAnchorElement>) => {
    const main = getPrimaryMain();
    if (!main) return;

    event.preventDefault();
    main.id = 'main-content';
    main.tabIndex = -1;
    main.focus({ preventScroll: true });
    main.scrollIntoView({ block: 'start' });
    window.history.replaceState(null, '', '#main-content');
  };

  return (
    <a className="skip-to-content" href="#main-content" onClick={skipToContent}>
      跳到主要内容
    </a>
  );
}
