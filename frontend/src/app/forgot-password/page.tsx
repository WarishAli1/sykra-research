"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const base = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
      const response = await fetch(`${base}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({ email }),
      });
      if (!response.ok) throw new Error("Unable to request a reset link.");
      setSent(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to request a reset link.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="min-h-screen bg-surface px-5 py-16 text-ink">
      <section className="mx-auto max-w-md rounded-3xl border border-line bg-white p-8 shadow-soft">
        <Link href="/login" className="text-sm text-ink-muted hover:text-ink">Back to sign in</Link>
        <h1 className="mt-8 font-serif text-4xl tracking-tight">Reset your password.</h1>
        <p className="mt-3 text-sm leading-6 text-ink-muted">We&apos;ll send a single-use reset link if an account matches.</p>
        {sent ? (
          <p className="mt-8 rounded-xl border border-mint bg-mint/30 px-4 py-3 text-sm">If the account exists, reset instructions are on their way.</p>
        ) : (
          <form className="mt-8 space-y-5" onSubmit={submit}>
            <label className="block text-sm font-semibold">Email<input className="mt-2 w-full rounded-xl border border-line bg-surface px-4 py-3 outline-none focus:border-forest" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            {error && <p role="alert" className="text-sm text-danger">{error}</p>}
            <button className="button-primary w-full justify-center disabled:opacity-60" disabled={pending}>{pending ? "Sending…" : "Send reset link"}</button>
          </form>
        )}
      </section>
    </main>
  );
}
