"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, X } from "lucide-react";

export function ConfirmDialog({
  open,
  title,
  body,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  body: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [pending, setPending] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    confirmRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pending) onCancel();
      if (event.key === "Enter" && !pending) void submit();
      if (event.key === "Tab") {
        const dialog = confirmRef.current?.closest("[role=alertdialog]");
        const focusable = dialog ? Array.from(dialog.querySelectorAll<HTMLElement>("button:not([disabled])")) : [];
        if (!focusable.length) return;
        const index = focusable.indexOf(document.activeElement as HTMLElement);
        const next = focusable[(index + (event.shiftKey ? -1 : 1) + focusable.length) % focusable.length];
        event.preventDefault();
        next?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, pending]);
  if (!open) return null;
  async function submit() {
    if (pending) return;
    setPending(true);
    try {
      await onConfirm();
    } finally {
      setPending(false);
    }
  }
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-forest/30 p-5 backdrop-blur-sm animate-[fade-in_.15s_ease-out]" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !pending) onCancel(); }}>
    <section role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" className="w-full max-w-md scale-100 rounded-2xl border border-line bg-white p-6 shadow-2xl animate-[scale-in_.15s_ease-out]">
      <div className="flex items-start justify-between gap-4"><div><h2 id="confirm-title" className="font-serif text-2xl text-ink">{title}</h2><p className="mt-3 text-sm leading-6 text-ink-muted">{body}</p></div><button onClick={onCancel} disabled={pending} aria-label="Close" className="rounded-lg p-1 text-ink-soft hover:bg-paper"><X className="h-4 w-4" /></button></div>
      <div className="mt-7 flex justify-end gap-3"><button onClick={onCancel} disabled={pending} className="rounded-full px-4 py-2 text-sm font-semibold text-ink-soft hover:bg-paper">Cancel</button><button ref={confirmRef} onClick={() => void submit()} disabled={pending} className="flex min-w-24 items-center justify-center gap-2 rounded-full bg-danger px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60">{pending && <Loader2 className="h-4 w-4 animate-spin" />}Delete</button></div>
    </section>
  </div>;
}

export function NameDialog({
  open,
  title,
  initialValue,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  title: string;
  initialValue: string;
  onCancel: () => void;
  onSubmit: (name: string) => Promise<void>;
}) {
  const [value, setValue] = useState(initialValue);
  const [pending, setPending] = useState(false);
  useEffect(() => { if (open) setValue(initialValue); }, [open, initialValue]);
  if (!open) return null;
  async function submit() {
    const name = value.trim();
    if (!name || pending) return;
    setPending(true);
    try { await onSubmit(name); } finally { setPending(false); }
  }
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-forest/30 p-5 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget && !pending) onCancel(); }}>
    <form onSubmit={(event) => { event.preventDefault(); void submit(); }} className="w-full max-w-sm rounded-2xl border border-line bg-white p-6 shadow-2xl"><h2 className="font-serif text-2xl text-ink">{title}</h2><input autoFocus value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") onCancel(); }} className="mt-5 w-full rounded-xl border border-line bg-surface px-4 py-3 text-sm outline-none focus:border-forest focus:ring-2 focus:ring-mint" /><div className="mt-6 flex justify-end gap-3"><button type="button" onClick={onCancel} className="rounded-full px-4 py-2 text-sm font-semibold text-ink-soft hover:bg-paper">Cancel</button><button disabled={pending || !value.trim()} className="button-primary">{pending ? "Saving…" : "Save"}</button></div></form>
  </div>;
}
