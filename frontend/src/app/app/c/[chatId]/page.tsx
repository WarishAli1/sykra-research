"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";

type StoredMessage = { id: string; role: string; content: string; created_at: string };

export default function StoredChatPage() {
  const params = useParams<{ chatId: string }>();
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    api.getChat(params.chatId).then((value) => setMessages(value)).catch(() => setMissing(true));
  }, [params.chatId]);
  return <main className="min-h-screen bg-paper px-6 py-8 text-ink"><div className="mx-auto max-w-3xl"><Link href="/app" className="inline-flex items-center gap-2 text-sm text-ink-soft hover:text-ink"><ArrowLeft className="h-4 w-4" /> Back to workspace</Link><h1 className="mt-10 font-serif text-4xl">Saved conversation</h1>{missing ? <p className="mt-8 text-sm text-ink-soft">Chat not found.</p> : <div className="mt-8 space-y-4">{messages.map((message) => <article key={message.id} className={`rounded-2xl border border-line p-5 ${message.role === "user" ? "bg-mint/30" : "bg-white"}`}><p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-soft">{message.role}</p><p className="whitespace-pre-wrap text-sm leading-7">{message.content}</p></article>)}</div>}</div></main>;
}
