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

export type ConfidenceLevel = "high" | "medium" | "low";
export type UncertaintyLevel = "low" | "moderate" | "high";

export type DynamicConfidence = {
  evidence_quality: ConfidenceLevel;
  answer_confidence: ConfidenceLevel;
  prediction_confidence?: ConfidenceLevel | null;
  recommendation_confidence?: ConfidenceLevel | null;
  data_completeness: ConfidenceLevel;
  uncertainty: UncertaintyLevel;
  explanation: string;
};

export type ReportSection = {
  module_id: string;
  title: string;
  content: string;
  cited_paper_ids: string[];
  evidence_status: "strong" | "mixed" | "weak" | "none" | "not_applicable";
  confidence: ConfidenceLevel;
};

export type ReportModulePlan = {
  module_id: string;
  title: string;
  importance: number;
  order?: number;
  target_words?: number;
};

export type ReportPlan = {
  primary_intent: string;
  secondary_intents?: string[];
  information_needs: string[];
  complexity_score: number;
  depth: "low" | "medium" | "high";
  target_words: number;
  reference_policy?: string;
  reasoning_policy?: string;
  domain_guardrails?: string[];
  modules: ReportModulePlan[];
  latency_notice?: string | null;
};

export type TurnArtifacts = {
  chartUrl?: string | null;
  chartSpecRaw?: string | null;
  comparisonTableMarkdown?: string | null;
  comparisonTableCaption?: string | null;
  graphEntities?: Array<Record<string, unknown>>;
};

export type ChatTurn = {
  role: "user" | "assistant";
  id: string;
  turnId?: string;
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
  statusSteps?: StatusStep[];
  requestId?: string;
  filename?: string;
  sourceQuery?: string;
  sourceEvidenceMode?: EvidenceMode;
  chartUrl?: string | null;
  /* Quick preview answer streamed before the full report */
  previewText?: string;
  /* Late artifacts (chart, comparison table, graph entities) */
  artifacts?: TurnArtifacts;
  /* Dynamic report */
  reportNotice?: string | null;
  reportPlan?: ReportPlan | null;
  sections?: ReportSection[];
  dynamicConfidence?: DynamicConfidence | null;
  informationNeeds?: string[];
  complexityScore?: number;
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
  /* Dynamic report */
  report_plan?: ReportPlan | null;
  sections?: ReportSection[];
  dynamic_confidence?: DynamicConfidence | null;
  information_needs?: string[];
  complexity_score?: number;
  report_notice?: string | null;
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
  | { type: "progress"; label: string; stage?: string; detail?: string; items?: string[] }
  | { type: "token"; text: string; kind?: "preview" | "final" }
  | { type: "result"; payload: ChatResponse }
  | { type: "notice"; message: string }
  | { type: "artifact"; artifact_type: "chart"; url: string; raw_spec?: string | null }
  | { type: "artifact"; artifact_type: "comparison_table"; markdown: string; caption?: string | null }
  | { type: "artifact"; artifact_type: "graph_entities"; entities: Array<Record<string, unknown>> }
  | { type: "filename"; filename: string }
  | { type: "done" }
  | { type: "cancelled" }
  | { type: "error"; message: string };

export type StatusStep = {
  stage: string;
  label: string;
  detail?: string;
  items?: string[];
};

export type UploadStreamEvent =
  | { type: "progress"; label: string; stage?: string }
  | { type: "result"; payload: UploadResponse }
  | { type: "error"; message: string }
  | { type: "cancelled" };

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

export type GraphNode = {
  id: string; name: string; type: string; val: number;
  source?: string; published?: string; authors?: string[];
  citation_count?: number; excerpt?: string;
};
export type GraphLink = { source: string; target: string; type: string; weight?: number };
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