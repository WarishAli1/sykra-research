export type ResponseMode = "normal" | "researched";
export type EvidenceMode = "literature" | "uploaded" | "blended";

export interface ReferenceEntry {
  id: number;
  title: string;
  authors: string[];
  link: string;
  published?: string | null;
  source: string;
  source_role?: string | null;
  why_cited?: string | null;
  support_level?: string | null;
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


export type GraphStats = {
  nodes: number; links: number; papers: number; concepts: number;
  methods: number; datasets: number; density: number; avg_degree: number;
  top_concept: string | null;
  top_paper: { id: string; name: string; citation_count: number } | null;
  min_year: number | null; max_year: number | null;
};
export type LegendEntry = { name: string; cluster?: number; kind?: "method" | "dataset" | "paper" };
export type NodeRel = { concepts: string[]; methods: string[]; datasets: string[]; papers: { id: string; name: string }[] };
export type GraphViewRequest = { scope: GraphScope; paper_links?: string[]; max_year?: number | null };
export type GraphViewResponse = {
  nodes: GraphNode[]; links: GraphLink[]; stats: GraphStats;
  global_stats: GraphStats; legend: LegendEntry[]; rel: Record<string, NodeRel>;
};
export type GraphPathRequest = GraphViewRequest & { a: string; b: string };
export type GraphPathResponse = { path: { nodes: string[]; links: [string, string][]; hops: number } | null };
export type SuggestMatch = { id: string; name: string; type: string; score: number };


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
  previewText?: string;
  artifacts?: TurnArtifacts;
  reportNotice?: string | null;
  reportPlan?: ReportPlan | null;
  sections?: ReportSection[];
  informationNeeds?: string[];
  complexityScore?: number;
  disclaimer?: string | null;
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
  disclaimer?: string | null;              
  papers_below_threshold: number;
  graph_contradictions?: Array<Record<string, unknown>>;
  graph_entities?: Array<Record<string, unknown>>;
  response_mode: ResponseMode;
  references: ReferenceEntry[];
  chart_url?: string | null;
  filename?: string | null;
  citation_audit?: Array<Record<string, unknown>>;     
  math_verification?: Record<string, unknown> | null;  
  primary_source_present?: boolean | null;            
  report_plan?: ReportPlan | null;
  sections?: ReportSection[];
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
  paper_links: string[];
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
  degree?: number; cluster?: number | null; year?: number | null;
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

export type StudioVisualType = "chart" | "flowchart" | "dfd" | "architecture" | "diagram";
export type StudioChartType = "bar" | "line" | "pie" | "scatter";
export type StudioGroundingLevel =
  | "user_provided"
  | "grounded"
  | "mixed"
  | "illustrative"
  | "draft";
export type StudioDataPath = "manual" | "papers" | "web_search";

export type StudioProvenance = {
  kind:
    | "user_provided"
    | "grounded"
    | "derived"
    | "illustrative"
    | "user_edited"
    | "ai_proposed";
  source_paper_id?: number | null;
  source_ref_id?: number | null;
  source_url?: string | null;
  source_quote?: string | null;
  derivation?: string | null;
  note?: string | null;
};

export type StudioChartSeries = {
  label: string;
  values: (number | null)[];
  x_values?: (number | null)[];
  unit?: string | null;
  provenance: StudioProvenance[];
};

export type StudioChartPayload = {
  kind: "chart";
  chart_type: StudioChartType;
  categories: string[];
  series: StudioChartSeries[];
  x_label?: string | null;
  y_label?: string | null;
  log_y?: boolean;
  show_values?: boolean;
};

export type StudioDiagramNode = {
  id: string;
  label: string;
  node_type?: "process" | "terminal" | "data" | "external" | "store" | "decision";
  layer?: number | null;
  provenance?: StudioProvenance | null;
};

export type StudioDiagramEdge = {
  source: string;
  target: string;
  label?: string | null;
};

export type StudioDiagramPayload = {
  kind: "flowchart" | "architecture" | "dfd" | "diagram";
  layout?: "top_down" | "left_right" | "layered";
  nodes: StudioDiagramNode[];
  edges: StudioDiagramEdge[];
  dfd_level?: 0 | 1 | null;
};

export type StudioGroundingSummary = {
  level: StudioGroundingLevel;
  grounded_count: number;
  user_provided_count: number;
  illustrative_count: number;
  ai_proposed_count?: number;
  citations: number[];
  note?: string | null;
};

export type StudioVisualSpec = {
  spec_version: number;
  visual_id: string;
  session_id: string;
  turn_id?: string | null;
  revision: number;
  title: string;
  caption?: string | null;
  grounding: StudioGroundingSummary;
  payload: StudioChartPayload | StudioDiagramPayload;
  created_at: string;
  asset_path?: string | null;
};

export type StudioGenerateRequest = {
  spec: StudioVisualSpec;
};

export type StudioGenerateResponse = {
  visual_id: string;
  revision: number;
  asset_path: string;
  grounding: StudioGroundingSummary;
};

export type StudioSessionListResponse = {
  visuals: StudioVisualSpec[];
};

export type StudioDraftSource =
  | "prompt"
  | "manual"
  | "papers"
  | "conversation"
  | "web_search";

export type StudioDraftRequest = {
  session_id: string;
  family: StudioVisualType;
  prompt: string;
  source?: StudioDraftSource;
  chart_type?: StudioChartType;
  dfd_level?: 0 | 1 | null;
  conversation_context?: string | null;
  selected_paper_links?: string[] | null;
};

export type StudioDraftResponse = {
  spec: StudioVisualSpec;
  asset_path: string | null;
  grounding: StudioGroundingSummary;
  warnings: string[];
  missing_data: string[];
};

export type StudioConversationContext = {
  excerpt: string;
  papers: string[];
};