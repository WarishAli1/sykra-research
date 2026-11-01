import type { DiagramDocument } from "@/features/studio/core/document";

const API_BASE_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/diagrams${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    throw new Error(`Diagram request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export type SavedDiagram = { id: string; title: string; document: DiagramDocument };

export const diagramApi = {
  list(sessionId: string): Promise<{ documents: SavedDiagram[] }> {
    return request(`/session/${encodeURIComponent(sessionId)}`);
  },
  create(sessionId: string, document: DiagramDocument): Promise<SavedDiagram> {
    return request("", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, title: document.title, document }),
    });
  },
  update(id: string, sessionId: string, document: DiagramDocument): Promise<SavedDiagram> {
    return request(`/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ session_id: sessionId, title: document.title, document }),
    });
  },
};
