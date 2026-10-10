"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const base = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
    const response = await fetch(`${base}/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ token, password }),
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: string };
      setError(body.detail ?? "Unable to reset password.");
      return;
    }
    setDone(true);
  }

  return (
    <section className="mx-auto max-w-md rounded-3xl border border-line bg-white p-8 shadow-soft">
      <Link href="/login" className="text-sm text-ink-muted hover:text-ink">Back to sign in</Link>
      <h1 className="mt-8 font-serif text-4xl tracking-tight">Choose a new password.</h1>
      {done ? <p className="mt-8 rounded-xl border border-mint bg-mint/30 px-4 py-3 text-sm">Password updated. You can sign in now.</p> : (
        <form className="mt-8 space-y-5" onSubmit={submit}>
          <label className="block text-sm font-semibold">New password<input className="mt-2 w-full rounded-xl border border-line bg-surface px-4 py-3 outline-none focus:border-forest" type="password" minLength={12} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <button className="button-primary w-full justify-center">Update password</button>
        </form>
      )}
    </section>
  );
}

export default function ResetPasswordPage() {
  return <main className="min-h-screen bg-surface px-5 py-16 text-ink"><Suspense fallback={<p className="text-center">Loading…</p>}><ResetPasswordForm /></Suspense></main>;
}
