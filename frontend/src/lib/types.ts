export type Paper = {
  title: string;
  authors: string[];
  summary: string;
  link: string;
  published?: string | null;
  relevance_score?: number | null;
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
};

export type ChatRequest = {
  query: string;
  session_id?: string;
  upload_mode?: "none" | "blend" | "grounded_only";
  include_uploaded?: boolean;
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
};

export type FollowupRequest = {
  session_id: string;
  question: string;
};

export type FollowupResponse = {
  answer: string;
  sources: string[];
};

export type UploadResponse = {
  filename: string;
  chunks_indexed: number;
  status: string;
};

// --- Graph / /research API ---

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
