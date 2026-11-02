export type GenerationSnapshot = {
  id: string;
  content: string;
  status: string;
  citations: Record<string, unknown>;
};

type Listener = (snapshot: GenerationSnapshot) => void;
type Entry = { chatId: string; listeners: Set<Listener>; timer: ReturnType<typeof setInterval> | null };

const entries = new Map<string, Entry>();
const API_BASE = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");

async function poll(messageId: string, entry: Entry) {
  try {
    const response = await fetch(`${API_BASE}/chats/${encodeURIComponent(entry.chatId)}`, { credentials: "include" });
    if (!response.ok) return;
    const messages = await response.json() as GenerationSnapshot[];
    const message = messages.find((candidate) => candidate.id === messageId);
    if (!message) return;
    for (const listener of entry.listeners) listener(message);
    if (message.status !== "generating" && message.status !== "streaming") {
      if (entry.timer) clearInterval(entry.timer);
      entry.timer = null;
    }
  } catch {
    // The next poll retries; the persisted message remains the source of truth.
  }
}

export function watchGeneration(chatId: string, messageId: string, listener: Listener): () => void {
  let entry = entries.get(messageId);
  if (!entry) {
    entry = { chatId, listeners: new Set(), timer: null };
    entries.set(messageId, entry);
    entry.timer = setInterval(() => void poll(messageId, entry!), 1500);
    void poll(messageId, entry);
  }
  entry.listeners.add(listener);
  return () => {
    entry?.listeners.delete(listener);
  };
}
