"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function VerifyEmailResult() {
  const token = useSearchParams().get("token") ?? "";
  const [message, setMessage] = useState("Verifying your email…");

  useEffect(() => {
    const base = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
    fetch(`${base}/auth/verify-email?token=${encodeURIComponent(token)}`, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(async (response) => {
        if (!response.ok) throw new Error("This verification link is invalid or expired.");
        setMessage("Your email is verified. You can return to Sykra Research.");
      })
      .catch((cause) => setMessage(cause instanceof Error ? cause.message : "Verification failed."));
  }, [token]);

  return <section className="mx-auto max-w-md rounded-3xl border border-line bg-white p-8 text-center shadow-soft"><h1 className="font-serif text-4xl tracking-tight">Email verification</h1><p className="mt-5 text-sm leading-6 text-ink-muted">{message}</p><Link href="/app" className="button-primary mt-8 inline-flex">Open app</Link></section>;
}

export default function VerifyEmailPage() {
  return <main className="min-h-screen bg-surface px-5 py-16 text-ink"><Suspense fallback={<p className="text-center">Loading…</p>}><VerifyEmailResult /></Suspense></main>;
}
