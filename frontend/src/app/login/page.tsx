"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowLeft, ArrowRight, Check, Eye, EyeOff, LockKeyhole } from "lucide-react";
import { passwordIsValid, passwordRequirements, PASSWORD_MIN_LENGTH } from "@/lib/passwordPolicy";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [googleAuthEnabled, setGoogleAuthEnabled] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const firstInvalidRef = useRef<HTMLInputElement>(null);
  const requirements = passwordRequirements(password);
  const validateField = (field: string, value: string) => {
    if (field === "name" && mode === "signup" && !value.trim()) return "Enter your name";
    if (field === "email" && (!value.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))) return "Enter a valid email address";
    if (field === "password" && !value.trim()) return "Enter your password";
    if (field === "password" && mode === "signup" && value.length < PASSWORD_MIN_LENGTH) return `Use at least ${PASSWORD_MIN_LENGTH} characters`;
    return "";
  };
  const updateField = (field: "name" | "email" | "password", value: string) => {
    if (field === "name") setName(value);
    if (field === "email") setEmail(value);
    if (field === "password") setPassword(value);
    if (touched[field]) setFieldErrors((current) => ({ ...current, [field]: validateField(field, value) }));
  };
  const blurField = (field: "name" | "email" | "password", value: string) => {
    setTouched((current) => ({ ...current, [field]: true }));
    setFieldErrors((current) => ({ ...current, [field]: validateField(field, value) }));
  };
  useEffect(() => {
    setGoogleAuthEnabled(process.env.NEXT_PUBLIC_GOOGLE_AUTH_ENABLED === "true");
  }, []);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const nextErrors = {
      ...(mode === "signup" ? { name: validateField("name", name), password: validateField("password", password) } : {}),
      email: validateField("email", email),
    };
    setTouched({ name: mode === "signup", email: true, password: true });
    setFieldErrors(nextErrors);
    const firstInvalid = (["name", "email", "password"] as const).find((field) => nextErrors[field]);
    if (firstInvalid) {
      firstInvalidRef.current?.focus();
      return;
    }

    if (mode === "signup" && !passwordIsValid(password)) return;
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
                <img src="/sykra-logo.svg" alt="" width={32} height={32} className="h-8 w-8 object-contain" />
                Sykra Research
              </Link>
              <p className="eyebrow mb-3">{mode === "login" ? "Welcome back" : "Start your workspace"}</p>
              <h1 className="font-serif text-4xl leading-tight tracking-tight text-ink">{mode === "login" ? "Return to your research." : "Create your research workspace."}</h1>
              <p className="mt-3 text-sm leading-6 text-ink-muted">Pick up where you left off across your library, literature, and notes.</p>
            </div>
            <form className="space-y-5" noValidate onSubmit={submit}>
              {mode === "signup" && <label className="block text-sm font-semibold text-ink">Name<input ref={firstInvalidRef} value={name} onBlur={() => blurField("name", name)} onChange={(event) => updateField("name", event.target.value)} required placeholder="Your name" aria-invalid={Boolean(touched.name && fieldErrors.name)} aria-describedby={touched.name && fieldErrors.name ? "name-error" : undefined} className={inputClass(Boolean(touched.name && fieldErrors.name))} /><ErrorText id="name-error" message={touched.name ? fieldErrors.name : ""} /></label>}
              <label className="block text-sm font-semibold text-ink">
                Email
                <input ref={mode === "login" ? firstInvalidRef : undefined} type="email" value={email} onBlur={() => blurField("email", email)} onChange={(event) => updateField("email", event.target.value)} required placeholder="you@university.edu" aria-invalid={Boolean(touched.email && fieldErrors.email)} aria-describedby={touched.email && fieldErrors.email ? "email-error" : undefined} className={inputClass(Boolean(touched.email && fieldErrors.email))} />
                <ErrorText id="email-error" message={touched.email ? fieldErrors.email : ""} />
              </label>
              <label className="block text-sm font-semibold text-ink">
                Password
                <span className="relative mt-2 block"><input ref={mode === "signup" ? firstInvalidRef : undefined} type={showPassword ? "text" : "password"} value={password} onBlur={() => blurField("password", password)} onChange={(event) => updateField("password", event.target.value)} required minLength={PASSWORD_MIN_LENGTH} placeholder={`At least ${PASSWORD_MIN_LENGTH} characters`} aria-invalid={Boolean(touched.password && fieldErrors.password)} aria-describedby={mode === "signup" ? "password-requirements password-error" : "password-error"} className={`${inputClass(Boolean(touched.password && fieldErrors.password))} pr-11`} /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-soft hover:text-ink">{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></span>
                <ErrorText id="password-error" message={touched.password ? fieldErrors.password : ""} />
              </label>
              {mode === "signup" && (password.length > 0 || touched.password) && <ul id="password-requirements" className="space-y-1 text-xs" aria-label="Password requirements">{requirements.map((requirement) => <li key={requirement.label} className={`transition-colors duration-150 ${requirement.valid ? "text-forest" : "text-ink-soft"}`}><span aria-hidden="true">{requirement.valid ? <Check className="inline h-3.5 w-3.5" /> : "○"}</span>{" "}{requirement.label}</li>)}</ul>}
              {error && <p role="alert" className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}<button type="button" aria-label="Dismiss error" onClick={() => setError("")} className="ml-auto">×</button></p>}
              <button type="submit" disabled={pending} className="button-primary w-full justify-center disabled:opacity-60">{pending ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"} <ArrowRight className="h-4 w-4" /></button>
            </form>
            {mode === "login" && googleAuthEnabled && <a href={`${(process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "")}/auth/google/start`} className="mt-4 flex w-full items-center justify-center gap-3 rounded-full border border-line px-4 py-3 text-sm font-semibold text-ink hover:bg-paper-dim"><svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24"><path fill="#4285F4" d="M21.35 12.23c0-.71-.06-1.4-.18-2.05H12v3.88h5.24a4.48 4.48 0 0 1-1.94 2.94v2.45h3.14c1.84-1.7 2.91-4.2 2.91-7.22Z" /><path fill="#34A853" d="M12 21.75c2.63 0 4.84-.87 6.45-2.35l-3.14-2.45c-.87.58-1.98.92-3.31.92-2.54 0-4.7-1.72-5.47-4.03H3.28v2.53A9.75 9.75 0 0 0 12 21.75Z" /><path fill="#FBBC05" d="M6.53 13.84a5.86 5.86 0 0 1 0-3.68V7.63H3.28a9.75 9.75 0 0 0 0 8.74l3.25-2.53Z" /><path fill="#EA4335" d="M12 6.13c1.43 0 2.72.49 3.73 1.45l2.8-2.8C16.84 3.1 14.63 2.25 12 2.25a9.75 9.75 0 0 0-8.72 5.38l3.25 2.53C7.3 7.85 9.46 6.13 12 6.13Z" /></svg>Continue with Google</a>}
            {mode === "login" && <Link href="/forgot-password" className="mt-4 block text-center text-sm font-semibold text-forest hover:underline">Forgot your password?</Link>}
            <div className="mt-6 flex items-center justify-center gap-2 text-xs text-ink-muted"><LockKeyhole className="h-3.5 w-3.5" /> Secure access to your workspace</div>
            <p className="mt-8 text-center text-sm text-ink-muted">{mode === "login" ? "New to Sykra?" : "Already have an account?"}{" "}<button type="button" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); setTouched({}); setFieldErrors({}); }} className="font-semibold text-forest hover:underline">{mode === "login" ? "Create an account" : "Sign in"}</button></p>
          </section>
        </div>
      </div>
    </main>
  );
}

function inputClass(invalid: boolean) {
  return `mt-2 w-full rounded-xl border bg-surface px-4 py-3 text-sm outline-none transition focus:ring-2 ${invalid ? "border-danger focus:border-danger focus:ring-danger/20" : "border-line focus:border-forest focus:ring-mint"}`;
}

function ErrorText({ id, message }: { id: string; message?: string }) {
  return <div className={`overflow-hidden text-[13px] font-normal text-danger transition-all duration-150 ${message ? "mt-1 max-h-8 opacity-100" : "max-h-0 opacity-0"}`}><p id={id} role="alert" className="flex items-center gap-1"><AlertCircle className="h-3.5 w-3.5 shrink-0" />{message || "\u00a0"}</p></div>;
}
