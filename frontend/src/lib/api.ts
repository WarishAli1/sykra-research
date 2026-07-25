import type {
  ChatRequest,
  ChatResponse,
  ClustersResponse,
  ContradictionsResponse,
  FocusModeResponse,
  FollowupRequest,
  FollowupResponse,
  FullGraphData,
  PdfExportRequest,
  RegenerateRequest,
  SessionPapersResponse,
  StreamEvent,
  UploadResponse,
  UploadStreamEvent,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const API_BASE_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
const BACKEND_ORIGIN = API_BASE_URL.replace(/\/api$/, "");

export function resolveAssetUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;
  return `${BACKEND_ORIGIN}${path.startsWith("/") ? "" : "/"}${path}`;
}

export class ApiAbortError extends Error {
  constructor() {
    super("Request was cancelled.");
    this.name = "ApiAbortError";
  }
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiAbortError();
    }
    throw e;
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;

    try {
      const data = (await response.json()) as { detail?: string | { message?: string } };
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail && typeof data.detail === "object" && "message" in data.detail) {
        message = data.detail.message ?? message;
      }
    } catch {
      const text = await response.text();
      if (text) message = text;
    }

    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}

async function requestBlob(path: string, init: RequestInit): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (typeof data.detail === "string") message = data.detail;
    } catch {
    }
    throw new ApiError(message, response.status);
  }

  return await response.blob();
}

function queryString(params: Record<string, string | undefined>): string {
  const searchParams = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value) searchParams.set(key, value);
  }

  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

async function streamRequest<T>(
  path: string,
  init: RequestInit,
  onEvent: (event: T) => void
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiAbortError();
    }
    throw e;
  }

  if (!response.ok || !response.body) {
    let message = `Request failed with status ${response.status}`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (typeof data.detail === "string") message = data.detail;
    } catch {
    }
    throw new ApiError(message, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;

        const jsonStr = line.slice(5).trim();
        if (!jsonStr) continue;

        try {
          const parsed = JSON.parse(jsonStr) as T;
          onEvent(parsed);
        } catch {
        }
      }
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiAbortError();
    }
    throw e;
  }
}

export const api = {
  chat(payload: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
    return request<ChatResponse>("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  },

  chatStream(payload: ChatRequest, onEvent: (event: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
    return streamRequest(
      "/chat/stream",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal,
      },
      onEvent
    );
  },

  followup(payload: FollowupRequest, signal?: AbortSignal): Promise<FollowupResponse> {
    return request<FollowupResponse>("/followup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  },

  followupStream(payload: FollowupRequest, onEvent: (event: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
    return streamRequest(
      "/followup/stream",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal,
      },
      onEvent
    );
  },

  cancelStream(requestId: string): Promise<{ cancelled: boolean }> {
    return request<{ cancelled: boolean }>(`/chat/cancel/${encodeURIComponent(requestId)}`, {
      method: "POST",
    });
  },

  cancelUploadStream(requestId: string): Promise<{ cancelled: boolean }> {
    return request<{ cancelled: boolean }>(`/upload/cancel/${encodeURIComponent(requestId)}`, {
      method: "POST",
    });
  },

  chatRegenerate(payload: RegenerateRequest, signal?: AbortSignal): Promise<ChatResponse> {
    return request<ChatResponse>("/chat/regenerate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  },

  uploadPdf(file: File, sessionId: string): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append("file", file);

    return request<UploadResponse>(`/upload${queryString({ session_id: sessionId })}`, {
      method: "POST",
      body: formData,
    });
  },

  getClusters(sessionId: string): Promise<ClustersResponse> {
    return request<ClustersResponse>(`/graph/${encodeURIComponent(sessionId)}/clusters`, {
      method: "GET",
    });
  },

  getFocus(paperLink: string): Promise<FocusModeResponse> {
    return request<FocusModeResponse>(
      `/graph/paper/focus${queryString({ paper_link: paperLink })}`,
      { method: "GET" }
    );
  },

  getContradictions(sessionId: string): Promise<ContradictionsResponse> {
    return request<ContradictionsResponse>(
      `/graph/${encodeURIComponent(sessionId)}/contradictions`,
      { method: "GET" }
    );
  },

  getSessionPapers(sessionId: string): Promise<SessionPapersResponse> {
    return request<SessionPapersResponse>(`/graph/${encodeURIComponent(sessionId)}/papers`, {
      method: "GET",
    });
  },

  // Conversation-level knowledge graph: everything discussed in the session.
  getFullGraph(sessionId: string): Promise<FullGraphData> {
    return request<FullGraphData>(`/graph/${encodeURIComponent(sessionId)}/full`, {
      method: "GET",
    });
  },

  // NEW — Message-level knowledge graph: only what a specific turn discussed.
  getTurnGraph(sessionId: string, turnId: string): Promise<FullGraphData> {
    return request<FullGraphData>(
      `/graph/${encodeURIComponent(sessionId)}/turn/${encodeURIComponent(turnId)}/full`,
      { method: "GET" }
    );
  },

  exportPdf(payload: PdfExportRequest): Promise<Blob> {
    return requestBlob("/export/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  uploadPdfStream(file: File, sessionId: string, onEvent: (event: UploadStreamEvent) => void, signal?: AbortSignal, requestId?: string): Promise<void> {
    const formData = new FormData();
    formData.append("file", file);
    return streamRequest(
      `/upload/stream${queryString({ session_id: sessionId, request_id: requestId })}`,
      { method: "POST", body: formData, signal },
      onEvent
    );
  },

  getFilename(turnId: string): Promise<{ turn_id: string; filename: string | null }> {
    return request(`/filename/${encodeURIComponent(turnId)}`, { method: "GET" });
  },

  deleteUploadedPdf(sessionId: string, link: string) {
    return request<{ success: boolean }>(
      `/uploads/${sessionId}?link=${encodeURIComponent(link)}`,
      {
        method: "DELETE",
      }
    );
  },

};

