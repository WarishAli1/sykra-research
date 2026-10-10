"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, ArrowRight, LockKeyhole } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const base = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
      const response = await fetch(`${base}/auth/${mode}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({ email, password, ...(mode === "signup" ? { name } : {}) }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? "Invalid email or password.");
      }
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next?.startsWith("/") ? next : "/app");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to sign in.");
    } finally {
      setPending(false);
    }
  };
  return (
    <main className="min-h-screen bg-surface px-5 py-6 text-ink">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-6xl flex-col">
        <Link href="/" className="inline-flex w-fit items-center gap-2 text-sm font-medium text-ink-muted transition-colors hover:text-ink">
          <ArrowLeft className="h-4 w-4" /> Back to home
        </Link>
        <div className="flex flex-1 items-center justify-center py-16">
          <section className="w-full max-w-md rounded-3xl border border-line bg-white p-7 shadow-soft sm:p-10">
            <div className="mb-8">
              <Link href="/" className="mb-8 inline-flex items-center gap-2 font-serif text-xl font-semibold tracking-tight text-ink">
                <span className="grid h-8 w-8 place-items-center rounded-xl bg-forest text-xs font-sans font-bold text-mint">S</span>
                Sykra Research
              </Link>
              <p className="eyebrow mb-3">{mode === "login" ? "Welcome back" : "Start your workspace"}</p>
              <h1 className="font-serif text-4xl leading-tight tracking-tight text-ink">{mode === "login" ? "Return to your research." : "Create your research workspace."}</h1>
              <p className="mt-3 text-sm leading-6 text-ink-muted">Pick up where you left off across your library, literature, and notes.</p>
            </div>
            <form className="space-y-5" onSubmit={submit}>
              {mode === "signup" && <label className="block text-sm font-semibold text-ink">Name<input value={name} onChange={(event) => setName(event.target.value)} required placeholder="Your name" className="mt-2 w-full rounded-xl border border-line bg-surface px-4 py-3 text-sm outline-none transition focus:border-forest focus:ring-2 focus:ring-mint" /></label>}
              <label className="block text-sm font-semibold text-ink">
                Email
                <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required placeholder="you@university.edu" className="mt-2 w-full rounded-xl border border-line bg-surface px-4 py-3 text-sm outline-none transition focus:border-forest focus:ring-2 focus:ring-mint" />
              </label>
              <label className="block text-sm font-semibold text-ink">
                Password
                <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={12} placeholder="At least 12 characters" className="mt-2 w-full rounded-xl border border-line bg-surface px-4 py-3 text-sm outline-none transition focus:border-forest focus:ring-2 focus:ring-mint" />
              </label>
              {error && <p role="alert" className="rounded-xl border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">{error}</p>}
              <button type="submit" disabled={pending} className="button-primary w-full justify-center disabled:opacity-60">{pending ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"} <ArrowRight className="h-4 w-4" /></button>
            </form>
            {mode === "login" && process.env.NEXT_PUBLIC_GOOGLE_AUTH_ENABLED === "true" && <a href={`${(process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "")}/auth/google/start`} className="mt-4 flex w-full items-center justify-center rounded-full border border-line px-4 py-3 text-sm font-semibold text-ink hover:bg-paper-dim">Continue with Google</a>}
            {mode === "login" && <Link href="/forgot-password" className="mt-4 block text-center text-sm font-semibold text-forest hover:underline">Forgot your password?</Link>}
            <div className="mt-6 flex items-center justify-center gap-2 text-xs text-ink-muted"><LockKeyhole className="h-3.5 w-3.5" /> Secure access to your workspace</div>
            <p className="mt-8 text-center text-sm text-ink-muted">{mode === "login" ? "New to Sykra?" : "Already have an account?"}{" "}<button type="button" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }} className="font-semibold text-forest hover:underline">{mode === "login" ? "Create an account" : "Sign in"}</button></p>
          </section>
        </div>
      </div>
    </main>
  );
}
