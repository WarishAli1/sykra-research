import type { DiagramDocument } from "@/components/studio/core/document";

const API_BASE_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/diagrams${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    throw new Error(`Diagram request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export type SavedDiagram = { id: string; title: string; document: DiagramDocument };
export type AiDiagramOutput = {
  diagram_type: DiagramDocument["pages"][number]["diagramType"];
  title: string;
  nodes: Array<{ id: string; type: string; label: string }>;
  edges: Array<{ id: string; source: string; target: string; label?: string; type?: string }>;
};
export type DiagramPatch = { op: "add_node" | "update_node" | "remove_node" | "add_edge" | "update_edge" | "remove_edge"; id: string; value?: Record<string, unknown> };

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
  generate(sessionId: string, diagramType: DiagramDocument["pages"][number]["diagramType"], instruction: string): Promise<AiDiagramOutput> {
    return request("/ai/generate", { method: "POST", body: JSON.stringify({ session_id: sessionId, diagram_type: diagramType, instruction }) });
  },
  edit(sessionId: string, document: DiagramDocument, instruction: string): Promise<{ patches: DiagramPatch[] }> {
    return request("/ai/edit", { method: "POST", body: JSON.stringify({ session_id: sessionId, document, instruction }) });
  },
};
