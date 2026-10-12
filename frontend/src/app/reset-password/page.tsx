"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useRef, useState } from "react";
import { AlertCircle, Check, Eye, EyeOff } from "lucide-react";
import { passwordIsValid, passwordRequirements, PASSWORD_MIN_LENGTH } from "@/lib/passwordPolicy";

function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [touched, setTouched] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);
  const requirements = passwordRequirements(password);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!passwordIsValid(password)) {
      setTouched(true);
      passwordRef.current?.focus();
      return;
    }
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
      <Link href="/" className="mt-8 inline-flex items-center gap-2 font-serif text-xl font-semibold tracking-tight text-ink"><img src="/sykra-logo.svg" alt="Sykra Research" width={32} height={32} className="h-8 w-8 object-contain" />Sykra Research</Link>
      <h1 className="mt-8 font-serif text-4xl tracking-tight">Choose a new password.</h1>
      {done ? <p className="mt-8 rounded-xl border border-mint bg-mint/30 px-4 py-3 text-sm">Password updated. You can sign in now.</p> : (
        <form className="mt-8 space-y-5" noValidate onSubmit={submit}>
          <label className="block text-sm font-semibold">New password<span className="relative mt-2 block"><input ref={passwordRef} className={`w-full rounded-xl border bg-surface px-4 py-3 pr-11 outline-none transition focus:ring-2 ${touched && !passwordIsValid(password) ? "border-danger focus:border-danger focus:ring-danger/20" : "border-line focus:border-forest focus:ring-mint"}`} type={showPassword ? "text" : "password"} minLength={PASSWORD_MIN_LENGTH} required value={password} onBlur={() => setTouched(true)} onChange={(event) => { setPassword(event.target.value); if (touched) setError(""); }} aria-invalid={touched && !passwordIsValid(password)} aria-describedby="password-requirements password-error" /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-soft hover:text-ink">{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></span><div className={`overflow-hidden text-[13px] font-normal text-danger transition-all duration-150 ${touched && !passwordIsValid(password) ? "mt-1 max-h-8 opacity-100" : "max-h-0 opacity-0"}`}><p id="password-error" role="alert" className="flex items-center gap-1"><AlertCircle className="h-3.5 w-3.5 shrink-0" />Use all password requirements</p></div></label>
          {password.length > 0 && <ul id="password-requirements" className="space-y-1 text-xs" aria-label="Password requirements">{requirements.map((requirement) => <li key={requirement.label} className={`transition-colors duration-150 ${requirement.valid ? "text-forest" : "text-ink-soft"}`}><span aria-hidden="true">{requirement.valid ? <Check className="inline h-3.5 w-3.5" /> : "○"}</span>{" "}{requirement.label}</li>)}</ul>}
          {error && <p role="alert" className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}<button type="button" aria-label="Dismiss error" onClick={() => setError("")} className="ml-auto">×</button></p>}
          <button className="button-primary w-full justify-center">Update password</button>
        </form>
      )}
    </section>
  );
}

export default function ResetPasswordPage() {
  return <main className="min-h-screen bg-surface px-5 py-16 text-ink"><Suspense fallback={<p className="text-center">Loading…</p>}><ResetPasswordForm /></Suspense></main>;
}
