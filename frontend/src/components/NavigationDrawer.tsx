'use client';

import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import { useDialogFocus } from './useDialogFocus';

/** Native modal semantics keep the page inert and restore keyboard focus on close. */
export default function NavigationDrawer({ open, onClose, children, label }: {
  open: boolean; onClose: () => void; children: React.ReactNode; label: string;
}) {
  const { dialogRef: ref, onKeyDown } = useDialogFocus<HTMLDialogElement>(open, onClose);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  useEffect(() => {
    const media = window.matchMedia('(min-width: 768px)');
    const handleResize = () => { if (media.matches) onClose(); };
    media.addEventListener('change', handleResize);
    return () => media.removeEventListener('change', handleResize);
  }, [onClose]);
  return (
    <dialog ref={ref} onKeyDown={onKeyDown} aria-label={label} onCancel={onClose} onClose={onClose}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
      className="fixed inset-0 m-0 h-dvh max-h-none w-full max-w-none border-0 bg-transparent p-0 backdrop:bg-ink-900/40">
      <div className="navigation-drawer-panel relative h-full w-[min(320px,88vw)] bg-white shadow-xl">
        <button type="button" onClick={onClose} aria-label="关闭导航"
          className="absolute right-2 top-3 z-10 grid h-11 w-11 place-items-center rounded-sm bg-white text-gray-700 hover:bg-gray-100">
          <X size={20} />
        </button>
        {children}
      </div>
    </dialog>
  );
}
