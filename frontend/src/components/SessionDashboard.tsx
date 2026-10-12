"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, FolderKanban, List, MoreHorizontal, Pencil, Plus, Search, Trash2 } from "lucide-react";

export type DashboardSession = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  chat_count: number;
  paper_count: number;
};

export type DashboardChat = {
  id: string;
  title: string;
  session_id?: string;
  session_name?: string | null;
  updated_at: string;
};

function relativeTime(value: string, now: number) {
  if (!now) return "recently";
  const seconds = Math.max(0, (now - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function SessionDashboard({
  sessions,
  chats,
  userName,
  onOpen,
  onRename,
  onDelete,
  onCreateSession,
}: {
  sessions: DashboardSession[];
  chats: DashboardChat[];
  userName?: string | null;
  onOpen: (id: string) => void;
  onRename: (session: DashboardSession) => void;
  onDelete: (session: DashboardSession) => void;
  onCreateSession: () => void;
}) {
  const [greeting, setGreeting] = useState("Good evening");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"updated" | "name" | "papers">("updated");
  const [listView, setListView] = useState(false);
  const [now, setNow] = useState(0);

  useEffect(() => {
    const hour = new Date().getHours();
    setGreeting(`Good ${hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening"}`);
  }, []);
  useEffect(() => {
    setNow(Date.now());
  }, []);

  const filtered = useMemo(
    () =>
      sessions
        .filter((session) => session.name.toLowerCase().includes(search.toLowerCase()))
        .sort((a, b) =>
          sort === "name"
            ? a.name.localeCompare(b.name)
            : sort === "papers"
              ? b.paper_count - a.paper_count
              : new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
        ),
    [sessions, search, sort]
  );
  const mostRecentSession = sessions[0];
  const latestChat = mostRecentSession
    ? chats.find((chat) => chat.session_id === mostRecentSession.id)
    : undefined;
  const firstName = userName?.trim().split(/\s+/)[0] || "researcher";

  return (
    <main className="min-w-0 flex-1 overflow-y-auto bg-paper px-5 py-8 sm:px-10 sm:py-10">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="font-serif text-4xl tracking-tight sm:text-5xl">{greeting}, {firstName}</h1>
            <p className="mt-2 text-sm text-ink-soft">Keep your sources, conversations, and ideas moving forward.</p>
          </div>
          <div className="flex items-center gap-2">
            <a href="/" className="inline-flex h-9 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm text-ink-soft transition hover:border-ink-soft hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
              <ArrowLeft className="h-4 w-4" /> Website
            </a>
            <button onClick={onCreateSession} className="inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-3.5 text-sm font-semibold text-white transition hover:bg-accent/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
              <Plus className="h-4 w-4" /> New Session
            </button>
          </div>
        </header>

        {sessions.length > 0 && (
          <>
            <section className="mt-8 grid gap-3 sm:grid-cols-3">
              <StatCard label="Sessions" value={sessions.length} />
              <StatCard label="Papers" value={sessions.reduce((total, session) => total + session.paper_count, 0)} />
              <StatCard label="Chats" value={sessions.reduce((total, session) => total + session.chat_count, 0)} />
            </section>

            {mostRecentSession && (
              <section className="mt-9">
                <h2 className="font-serif text-2xl">Continue where you left off</h2>
                <div className="mt-4 flex flex-col gap-5 rounded-2xl border border-line bg-white p-5 shadow-soft sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-wide text-ink-soft/70">Most recent session</p>
                    <h3 className="mt-1 truncate font-serif text-2xl">{mostRecentSession.name}</h3>
                    <p className="mt-2 truncate text-sm text-ink-soft">{latestChat?.title || "No chats yet"} · {relativeTime(mostRecentSession.updated_at, now)}</p>
                    <p className="mt-1 text-xs text-ink-soft">{mostRecentSession.paper_count} {mostRecentSession.paper_count === 1 ? "paper" : "papers"}</p>
                  </div>
                  <button onClick={() => onOpen(latestChat ? `${mostRecentSession.id}/chat/${latestChat.id}` : mostRecentSession.id)} className="inline-flex h-9 shrink-0 items-center justify-center rounded-lg bg-forest px-4 text-sm font-semibold text-white hover:bg-forest/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">Resume</button>
                </div>
              </section>
            )}

            <section className="mt-9">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="font-serif text-2xl">Your Sessions</h2>
                <div className="ml-auto flex items-center gap-2">
                  <label className="flex h-9 items-center gap-2 rounded-lg border border-line bg-white px-2.5">
                    <Search className="h-3.5 w-3.5 text-ink-soft" />
                    <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search" className="w-24 bg-transparent text-xs outline-none sm:w-36" />
                  </label>
                  <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)} className="h-9 rounded-lg border border-line bg-white px-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-accent/40">
                    <option value="updated">Recently updated</option><option value="name">Name</option><option value="papers">Most papers</option>
                  </select>
                  <button onClick={() => setListView((value) => !value)} aria-label="Toggle session layout" className="rounded-lg border border-line bg-white p-2 text-ink-soft hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                    {listView ? <FolderKanban className="h-4 w-4" /> : <List className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <div className={`mt-4 grid gap-4 ${listView ? "" : "md:grid-cols-2 lg:grid-cols-3"}`}>
                {filtered.map((session) => <SessionCard key={session.id} session={session} onOpen={onOpen} onRename={onRename} onDelete={onDelete} listView={listView} now={now} />)}
                <button onClick={onCreateSession} className={`flex min-h-32 items-center justify-center gap-2 rounded-2xl border border-dashed border-ink-soft/40 text-sm font-medium text-ink-soft transition hover:border-accent hover:bg-gold-tint/30 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${listView ? "py-5" : ""}`}>
                  <Plus className="h-4 w-4" /> Create new session
                </button>
              </div>
            </section>
          </>
        )}

        {sessions.length === 0 && (
          <section className="mx-auto mt-16 max-w-xl text-center">
            <div className="mx-auto grid h-20 w-20 place-items-center rounded-3xl bg-mint"><img src="/sykra-logo.svg" alt="" className="h-12 w-12 object-contain" /></div>
            <h2 className="mt-6 font-serif text-3xl">A calm home for your research</h2>
            <p className="mt-3 text-sm leading-6 text-ink-soft">Create a session to gather papers, ask cited questions, and follow the ideas through your research graph.</p>
            <button onClick={onCreateSession} className="mt-7 inline-flex h-11 items-center gap-2 rounded-lg bg-accent px-5 text-sm font-semibold text-white hover:bg-accent/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"><Plus className="h-4 w-4" /> Create your first session</button>
          </section>
        )}
      </div>
    </main>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return <div className="rounded-xl border border-line bg-white px-4 py-3"><p className="text-xs text-ink-soft">{label}</p><p className="mt-1 font-serif text-2xl">{value}</p></div>;
}

function SessionCard({ session, onOpen, onRename, onDelete, listView, now }: { session: DashboardSession; onOpen: (id: string) => void; onRename: (session: DashboardSession) => void; onDelete: (session: DashboardSession) => void; listView: boolean; now: number }) {
  const [open, setOpen] = useState(false);
  return <article className={`group relative rounded-2xl border border-line bg-white p-5 shadow-soft transition hover:-translate-y-0.5 ${listView ? "flex items-center gap-5" : ""}`}>
    <button onClick={() => onOpen(session.id)} className="flex min-w-0 items-center gap-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-mint text-forest"><FolderKanban className="h-5 w-5" /></span>
      <span className="min-w-0"><span className="block truncate font-serif text-xl">{session.name}</span><span className="mt-1 block text-xs text-ink-soft">{relativeTime(session.updated_at, now)}</span></span>
    </button>
    <div className={`flex gap-4 text-xs text-ink-soft ${listView ? "ml-auto" : "mt-7"}`}><span>{session.paper_count} {session.paper_count === 1 ? "paper" : "papers"}</span><span>{session.chat_count} {session.chat_count === 1 ? "chat" : "chats"}</span></div>
    <div className="absolute right-3 top-3"><button onClick={() => setOpen((value) => !value)} aria-label="Session menu" aria-expanded={open} className={`rounded-lg p-1.5 hover:bg-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${open ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"}`}><MoreHorizontal className="h-4 w-4" /></button>{open && <div className="absolute right-0 top-8 z-30 w-32 rounded-xl border border-line bg-white p-1 shadow-xl"><button onClick={() => { setOpen(false); onRename(session); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs hover:bg-paper"><Pencil className="h-3.5 w-3.5" />Rename</button><button onClick={() => { setOpen(false); onDelete(session); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-danger hover:bg-danger/5"><Trash2 className="h-3.5 w-3.5" />Delete</button></div>}</div>
  </article>;
}
