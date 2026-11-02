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

type NameDialogProps = {
  open: boolean;
  title: string;
  initialValue: string;
  onCancel: () => void;
  onSubmit: (name: string) => Promise<void>;
};

type PromptDialogProps = {
  open: boolean;
  title: string;
  label: string;
  initialValue: string;
  maxLength?: number;
  error?: string;
  onCancel: () => void;
  onSubmit: (value: string) => void | Promise<void>;
};

export function PromptDialog({ open, ...rest }: PromptDialogProps) {
  if (!open) return null;
  return <PromptDialogBody {...rest} />;
}

function PromptDialogBody({
  title,
  label,
  initialValue,
  maxLength = 60,
  error,
  onCancel,
  onSubmit,
}: {
  title: string;
  label: string;
  initialValue: string;
  maxLength?: number;
  error?: string;
  onCancel: () => void;
  onSubmit: (value: string) => void | Promise<void>;
}) {
  const [value, setValue] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });
  }, []);
  const trimmed = value.trim();
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-forest/30 p-5 backdrop-blur-sm" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
    <form role="dialog" aria-modal="true" aria-labelledby="prompt-title" onSubmit={(event) => { event.preventDefault(); if (trimmed && trimmed !== initialValue.trim()) void onSubmit(trimmed); }} className="w-full max-w-md rounded-xl border border-line bg-paper p-6 shadow-2xl">
      <h2 id="prompt-title" className="font-serif text-2xl text-ink">{title}</h2>
      <label className="mt-5 block text-xs font-semibold text-ink-soft" htmlFor="prompt-value">{label}</label>
      <input ref={inputRef} id="prompt-value" value={value} maxLength={maxLength} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") onCancel(); }} className="mt-2 w-full rounded-xl border border-line bg-white px-4 py-3 text-sm outline-none focus:border-forest focus:ring-2 focus:ring-mint" />
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      <div className="mt-6 flex justify-end gap-3"><button type="button" onClick={onCancel} className="rounded-full px-4 py-2 text-sm font-semibold text-ink-soft hover:bg-white">Cancel</button><button type="submit" disabled={!trimmed || trimmed === initialValue.trim()} className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Rename</button></div>
    </form>
  </div>;
}

export function NameDialog({ open, ...rest }: NameDialogProps) {
  if (!open) return null;
  return <NameDialogBody {...rest} />;
}

function NameDialogBody({ title, initialValue, onCancel, onSubmit }: Omit<NameDialogProps, "open">) {
  const [value, setValue] = useState(initialValue);
  const [pending, setPending] = useState(false);
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