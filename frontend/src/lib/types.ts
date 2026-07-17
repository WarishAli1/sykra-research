export type ResponseMode = "normal" | "researched";

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
};

export type ChatRequest = {
  query: string;
  session_id?: string;
  upload_mode?: "none" | "blend" | "grounded_only";
  include_uploaded?: boolean;
  response_mode: ResponseMode;
};

export type ChatResponse = {
  answer: string;
  session_id: string;
  papers: Paper[];
  citations: string[];
  coverage_gaps: string[];
  domain_caveat?: string | null;
  papers_below_threshold: number;
  graph_contradictions?: Array<Record<string, unknown>>;
  graph_entities?: Array<Record<string, unknown>>;
  response_mode: ResponseMode;
  references: ReferenceEntry[];
};

export type FollowupRequest = {
  session_id: string;
  question: string;
  response_mode: ResponseMode;
};

export type FollowupResponse = {
  answer: string;
  sources: string[];
  references: ReferenceEntry[];
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

export interface PdfExportRequest {
  session_id: string;
  format: "standard" | "latex";
  answer: string;
  references: ReferenceEntry[];
  title?: string;
  turn_id?: string;
}
