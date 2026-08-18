import type {
  StudioVisualSpec,
  StudioGenerateResponse,
  StudioSessionListResponse,
  StudioGroundingSummary,
  StudioDraftRequest,
  StudioDraftResponse,
} from "./types";

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api"
).replace(/\/$/, "");

const BACKEND_ORIGIN = API_BASE_URL.replace(/\/api$/, "");

export function resolveStudioAsset(path: string | null | undefined): string | null {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;
  return `${BACKEND_ORIGIN}${path.startsWith("/") ? "" : "/"}${path}`;
}

class StudioApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "StudioApiError";
    this.status = status;
  }
}

async function studioRequest<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/studio${path}`, { ...init });
  if (!response.ok) {
    let message = `Studio request failed (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {}
    throw new StudioApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const studioApi = {
  generate(spec: StudioVisualSpec): Promise<StudioGenerateResponse> {
    return studioRequest<StudioGenerateResponse>("/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec }),
    });
  },

  generateGrounded(payload: {
    session_id: string;
    path: "papers" | "web_search";
    query: string;
    title: string;
    chartType: string;
  }): Promise<{ spec: StudioVisualSpec; asset_path: string; grounding: StudioGroundingSummary }> {
    return studioRequest("/generate/grounded", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  draft(payload: StudioDraftRequest): Promise<StudioDraftResponse> {
    return studioRequest<StudioDraftResponse>("/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  
  revise(visualId: string, spec: StudioVisualSpec): Promise<StudioGenerateResponse> {
    return studioRequest<StudioGenerateResponse>(`/${visualId}/revise`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
    });
  },

  getVisual(visualId: string): Promise<{ current: StudioVisualSpec; history: StudioVisualSpec[] }> {
    return studioRequest(`/${visualId}`, { method: "GET" });
  },

  listSession(sessionId: string): Promise<StudioSessionListResponse> {
    return studioRequest(`/session/${sessionId}`, { method: "GET" });
  },
};