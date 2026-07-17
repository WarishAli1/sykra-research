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
  ResearchRequest,
  ResearchResponse,
  SessionPapersResponse,
  UploadResponse,
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

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
  });

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
      // response wasn't JSON (likely a real PDF error page) — keep default message
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

export const api = {
  chat(payload: ChatRequest): Promise<ChatResponse> {
    return request<ChatResponse>("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  followup(payload: FollowupRequest): Promise<FollowupResponse> {
    return request<FollowupResponse>("/followup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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

  research(payload: ResearchRequest): Promise<ResearchResponse> {
    return request<ResearchResponse>("/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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

  getFullGraph(sessionId: string): Promise<FullGraphData> {
    return request<FullGraphData>(`/graph/${encodeURIComponent(sessionId)}/full`, {
      method: "GET",
    });
  },

  exportPdf(payload: PdfExportRequest): Promise<Blob> {
    return requestBlob("/export/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
};