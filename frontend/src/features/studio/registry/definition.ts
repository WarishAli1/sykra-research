import type { ComponentType } from "react";
import type { NodeProps } from "@xyflow/react";
import type { DiagramDocument, DiagramEdge, DiagramNode, DiagramPage } from "../core/document";

export type IssueSeverity = "error" | "warning" | "info";

export type DiagramIssue = {
  id: string;
  severity: IssueSeverity;
  message: string;
  targetIds: string[];
  ruleId: string;
  quickFix?: { label: string; command: DiagramCommand };
};

export type DiagramCommand =
  | { type: "add-node"; pageId: string; node: DiagramNode }
  | { type: "remove-edge"; pageId: string; edge: DiagramEdge }
  | { type: "update-edge"; pageId: string; edgeId: string; patch: Partial<DiagramEdge> }
  | { type: "dismiss-issue"; issueId: string };

export type PaletteItem = {
  id: string;
  label: string;
  nodeType?: DiagramNode["type"];
  edgeType?: string;
};

export type PaletteGroup = { id: string; label: string; items: PaletteItem[] };
export type ConnectionRule = (page: DiagramPage, source: DiagramNode, target: DiagramNode, edge: DiagramEdge) => DiagramIssue | null;
export type DocumentValidator = (document: DiagramDocument) => DiagramIssue[];
export type DiagramNodeComponent = ComponentType<NodeProps>;

export type DiagramTypeDefinition = {
  id: string;
  label: string;
  icon: string;
  description: string;
  palette: PaletteGroup[];
  nodeTypes: Record<string, DiagramNodeComponent>;
  edgeTypes: Record<string, object>;
  connectionRules: ConnectionRule[];
  validateDocument: DocumentValidator;
  templates: string[];
  ai: { enabled: false; systemPrompt: string };
  defaultStyles: Record<string, string>;
  quickAdd: Record<string, DiagramNode["type"][]>;
};
