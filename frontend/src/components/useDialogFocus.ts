'use client';

import { useEffect, useRef, type KeyboardEvent } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function focusableElements(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter((element) => !element.hasAttribute('inert') && element.getClientRects().length > 0);
}

/**
 * Gives a modal dialog the expected keyboard behavior without coupling it to
 * a particular visual implementation. The consumer must attach the returned
 * ref and onKeyDown handler to its dialog element.
 */
export function useDialogFocus<T extends HTMLElement>(isOpen: boolean, onClose: () => void) {
  const dialogRef = useRef<T>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    const activeElement = document.activeElement;
    restoreFocusRef.current = activeElement instanceof HTMLElement ? activeElement : null;
    const frame = window.requestAnimationFrame(() => {
      const dialog = dialogRef.current;
      if (!dialog) return;
      const [firstFocusable] = focusableElements(dialog);
      (firstFocusable ?? dialog).focus();
    });

    return () => {
      window.cancelAnimationFrame(frame);
      const restoreFocus = restoreFocusRef.current;
      if (restoreFocus?.isConnected) restoreFocus.focus();
      restoreFocusRef.current = null;
    };
  }, [isOpen]);

  const onKeyDown = (event: KeyboardEvent<T>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;

    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = focusableElements(dialog);
    if (focusable.length === 0) {
      event.preventDefault();
      dialog.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const activeElement = document.activeElement;
    if (event.shiftKey && (activeElement === first || !dialog.contains(activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (activeElement === last || !dialog.contains(activeElement))) {
      event.preventDefault();
      first.focus();
    }
  };

  return { dialogRef, onKeyDown };
}
