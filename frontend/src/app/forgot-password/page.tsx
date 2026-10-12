"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { AlertCircle, ArrowLeft, Check } from "lucide-react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [touched, setTouched] = useState(false);
  const emailInvalid = touched && (!email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email));
  const emailError = !email.trim() ? "Enter your email" : "Enter a valid email address";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (!email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return;
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
        {!sent && <Link href="/login" className="inline-flex items-center gap-2 text-sm text-ink-muted hover:text-ink"><ArrowLeft className="h-4 w-4" />Back to sign in</Link>}
        {!sent && <h1 className="mt-6 font-serif text-4xl tracking-tight">Reset your password.</h1>}
        <p className="mt-3 text-sm leading-6 text-ink-muted">Enter your email and we&apos;ll send a single-use reset link if an account matches.</p>
        {sent ? (
          <div className="mt-8 rounded-xl border border-mint bg-mint/30 px-4 py-5 text-center">
            <span className="mx-auto grid h-10 w-10 place-items-center rounded-full bg-mint text-forest"><Check className="h-5 w-5" /></span>
            <h1 className="mt-4 font-serif text-2xl">Check your email</h1>
            <p className="mt-2 text-sm text-ink-muted">If an account matches {email}, we&apos;ve sent a reset link.</p>
            <Link href="/login" className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-forest hover:underline"><ArrowLeft className="h-4 w-4" />Back to sign in</Link>
          </div>
        ) : (
          <form className="mt-8 space-y-5" noValidate onSubmit={submit}>
            <label className="block text-sm font-semibold">Email<input className={`mt-2 w-full rounded-xl border bg-surface px-4 py-3 outline-none transition focus:ring-2 ${emailInvalid ? "border-danger focus:border-danger focus:ring-danger/20" : "border-line focus:border-forest focus:ring-mint"}`} type="email" required value={email} onBlur={() => setTouched(true)} onChange={(event) => { setEmail(event.target.value); if (touched) setError(""); }} aria-invalid={emailInvalid} aria-describedby={emailInvalid ? "forgot-email-error" : undefined} /></label>
            <div className={`overflow-hidden text-[13px] text-danger transition-all duration-150 ${emailInvalid ? "max-h-8 opacity-100" : "max-h-0 opacity-0"}`}><p id="forgot-email-error" role="alert" className="flex items-center gap-1"><AlertCircle className="h-3.5 w-3.5" />{emailError}</p></div>
            {error && <p role="alert" className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}<button type="button" aria-label="Dismiss error" onClick={() => setError("")} className="ml-auto">×</button></p>}
            <button className="button-primary w-full justify-center disabled:opacity-60" disabled={pending}>{pending ? "Sending…" : "Send reset link"}</button>
          </form>
        )}
      </section>
    </main>
  );
}
