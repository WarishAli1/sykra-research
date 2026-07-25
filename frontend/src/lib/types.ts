export type ResponseMode = "normal" | "researched";
export type EvidenceMode = "literature" | "uploaded" | "blended";

export interface ReferenceEntry {
  id: number;
  title: string;
  authors: string[];
  link: string;
  published?: string | null;
  source: string;
}

export type Paper = {
  title: string;
  authors: string[];
  summary: string;
  link: string;
  published?: string | null;
  relevance_score?: number | null;
  source?: string;
  is_uploaded?: boolean;
  file_url?: string | null;
};

export type ChatTurn = {
  role: "user" | "assistant";
  id: string;
  turnId?: string; // backend turn_id, used to scope message-level KG queries
  text: string;
  papers?: Paper[];
  sources?: string[];
  citations?: string[];
  coverageGaps?: string[];
  domainCaveat?: string | null;
  papersBelowThreshold?: number;
  kind?: "chat" | "followup";
  references?: ReferenceEntry[];
  responseMode?: ResponseMode;
  streaming?: boolean;
  stopped?: boolean;
  statusLabel?: string;
  requestId?: string;
  filename?: string;
  sourceQuery?: string;
  sourceEvidenceMode?: EvidenceMode;
  chartUrl?: string | null; // seaborn chart image path, if one was generated
};

export type ChatRequest = {
  query: string;
  session_id?: string;
  turn_id?: string;
  evidence_mode?: EvidenceMode;
  response_mode: ResponseMode;
  request_id?: string;
  conversation_history?: { role: string; content: string }[];
};

export type ChatResponse = {
  answer: string;
  session_id: string;
  turn_id: string;
  papers: Paper[];
  citations: string[];
  coverage_gaps: string[];
  domain_caveat?: string | null;
  papers_below_threshold: number;
  graph_contradictions?: Array<Record<string, unknown>>;
  graph_entities?: Array<Record<string, unknown>>;
  response_mode: ResponseMode;
  references: ReferenceEntry[];
  chart_url?: string | null;
  filename?: string | null;
};

export type FollowupRequest = {
  session_id: string;
  turn_id?: string;
  question: string;
  response_mode: ResponseMode;
};

export type FollowupResponse = {
  answer: string;
  sources: string[];
  references: ReferenceEntry[];
  chart_url?: string | null;
};

export type RegenerateRequest = {
  query: string;
  session_id?: string;
  turn_id?: string;
  evidence_mode?: EvidenceMode;
  response_mode: ResponseMode;
  request_id?: string;
  is_followup?: boolean;
};

export type StreamEvent =
  | { type: "progress"; label: string }
  | { type: "token"; text: string }
  | { type: "result"; payload: ChatResponse }
  | { type: "cancelled" }
  | { type: "error"; message: string };

export type UploadStreamEvent =
  | {
      type: "progress";
      label: string;
      stage?: string;
    }
  | {
      type: "result";
      payload: UploadResponse;
    }
  | {
      type: "error";
      message: string;
    }
  | {
      type: "cancelled";
    };

export type UploadResponse = {
  filename: string;
  chunks_indexed: number;
  status: string;
  file_url: string;
  link: string;
};


export type ResearchRequest = {
  query: string;
  session_id?: string | null;
};

export type ResearchResponse = {
  answer: string;
  session_id: string;
  papers_processed: number;
};

export type ClusterOut = {
  concept: string;
  papers: string[];
  paper_count: number;
};

export type ClustersResponse = {
  clusters: ClusterOut[];
};

export type GraphPaperNode = {
  title?: string;
  link?: string;
  published?: string;
  source?: string;
  text_excerpt?: string;
  [key: string]: unknown;
};

export type FocusModeResponse = {
  paper?: GraphPaperNode;
  children: GraphPaperNode[];
  parents: GraphPaperNode[];
  concepts: string[];
  methods: string[];
};

export type ContradictionOut = {
  paper_a: string;
  paper_b: string;
  reason: string;
};

export type ContradictionsResponse = {
  contradictions: ContradictionOut[];
};

export type SessionPapersResponse = {
  papers: GraphPaperNode[];
};
export type GraphNode = { id: string; name: string; type: string; val: number };
export type GraphLink = { source: string; target: string; type: string };
export type FullGraphData = { nodes: GraphNode[]; links: GraphLink[] };

export type GraphScope = "message" | "conversation";

export interface PdfExportRequest {
  session_id: string;
  format: "standard" | "latex";
  answer: string;
  references: ReferenceEntry[];
  title?: string;
  turn_id?: string;
  chart_path?: string;
}