import { diagramDocumentSchema, type DiagramDocument } from "./document";

type LegacyDocument = {
  schemaVersion?: number;
  id: string;
  title: string;
  pages: Array<{
    id: string;
    name: string;
    diagramType?: string;
    nodes: Array<{ id: string; type?: string; position: { x: number; y: number }; label?: string }>;
    edges: Array<{ id: string; source: string; target: string; label?: string }>;
  }>;
  activePageId: string;
  updatedAt: string;
};

export function migrateDiagramDocument(value: unknown): DiagramDocument {
  const parsed = value as LegacyDocument;
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.pages)) {
    throw new Error("Invalid diagram document");
  }
  if ((parsed.schemaVersion ?? 1) === 2) return diagramDocumentSchema.parse(value);
  if ((parsed.schemaVersion ?? 1) !== 1) {
    throw new Error(`Unsupported diagram schema version: ${String(parsed.schemaVersion)}`);
  }
  return diagramDocumentSchema.parse({
    ...parsed,
    schemaVersion: 2,
    dismissedIssues: [],
    pages: parsed.pages.map((page) => ({
      ...page,
      diagramType: page.diagramType === "dfd" || page.diagramType === "architecture" ? page.diagramType : "flowchart",
      nodes: page.nodes.map((node) => ({ ...node, type: node.type ?? "process", label: node.label ?? "Untitled" })),
    })),
  });
}
