"use client";

import Link from "next/link";
import { ArrowLeft, LogOut, ShieldCheck } from "lucide-react";
import { FormEvent, useState } from "react";

export default function SettingsPage() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordMessage, setPasswordMessage] = useState("");
  async function logoutAll() {
    await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api"}/auth/logout-all`, {
      method: "POST",
      credentials: "include",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    window.location.href = "/login";
  }

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setPasswordMessage("");
    const base = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
    const response = await fetch(`${base}/auth/change-password`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    setPasswordMessage(response.ok ? "Password changed. Other sessions were signed out." : body.detail ?? "Unable to change password.");
    if (response.ok) {
      setCurrentPassword("");
      setNewPassword("");
    }
  }

  return <main className="min-h-screen bg-paper px-6 py-8 text-ink"><div className="mx-auto max-w-3xl">
    <Link href="/app" className="inline-flex items-center gap-2 text-sm text-ink-soft hover:text-ink"><ArrowLeft className="h-4 w-4" /> Back to app</Link>
    <h1 className="mt-10 font-serif text-4xl">Settings</h1>
    <p className="mt-2 text-sm text-ink-soft">Manage your Sykra Research workspace.</p>
    <section className="mt-10 rounded-2xl border border-line bg-paper-dim p-6"><h2 className="font-semibold">Security</h2><p className="mt-2 text-sm leading-6 text-ink-soft">Sessions use HttpOnly cookies and are stored server-side. Password changes, export, and account deletion are intentionally gated behind verified account workflows.</p><button onClick={logoutAll} className="mt-5 inline-flex items-center gap-2 rounded-full border border-danger/30 px-4 py-2 text-sm font-semibold text-danger hover:bg-danger/5"><LogOut className="h-4 w-4" /> Log out of all devices</button></section>
    <section className="mt-4 rounded-2xl border border-line bg-white p-6"><h2 className="font-semibold">Change password</h2><form onSubmit={changePassword} className="mt-4 grid gap-3 sm:max-w-md"><input type="password" required placeholder="Current password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="rounded-xl border border-line bg-paper-dim px-4 py-3 text-sm" /><input type="password" required minLength={12} placeholder="New password (12+ characters)" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="rounded-xl border border-line bg-paper-dim px-4 py-3 text-sm" /><button className="button-primary w-fit">Change password</button>{passwordMessage && <p role="status" className="text-sm text-ink-soft">{passwordMessage}</p>}</form></section>
    <section className="mt-4 flex items-start gap-3 rounded-2xl border border-line bg-white p-6"><ShieldCheck className="mt-0.5 h-5 w-5 text-indigo" /><div><h2 className="font-semibold">Account controls</h2><p className="mt-2 text-sm leading-6 text-ink-soft">Email verification, password reset, data export, and account deletion require a configured email provider and are tracked in the security roadmap.</p></div></section>
  </div></main>;
}
