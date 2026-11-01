import { z } from "zod";

export const diagramNodeSchema = z.object({
  id: z.string().min(1),
  type: z.enum(["start", "process", "decision", "data", "end"]).default("process"),
  position: z.object({ x: z.number(), y: z.number() }),
  label: z.string().max(500).default("Untitled"),
});

export const diagramEdgeSchema = z.object({
  id: z.string().min(1),
  source: z.string().min(1),
  target: z.string().min(1),
  label: z.string().max(200).optional(),
});

export const diagramPageSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1).max(100),
  diagramType: z.literal("flowchart"),
  nodes: z.array(diagramNodeSchema),
  edges: z.array(diagramEdgeSchema),
});

export const diagramDocumentSchema = z.object({
  schemaVersion: z.literal(1),
  id: z.string().min(1),
  title: z.string().min(1).max(200),
  pages: z.array(diagramPageSchema).min(1),
  activePageId: z.string().min(1),
  updatedAt: z.string(),
});

export type DiagramNode = z.infer<typeof diagramNodeSchema>;
export type DiagramEdge = z.infer<typeof diagramEdgeSchema>;
export type DiagramPage = z.infer<typeof diagramPageSchema>;
export type DiagramDocument = z.infer<typeof diagramDocumentSchema>;

export function createFlowchartDocument(): DiagramDocument {
  const pageId = crypto.randomUUID();
  return {
    schemaVersion: 1,
    id: crypto.randomUUID(),
    title: "Untitled flowchart",
    activePageId: pageId,
    updatedAt: new Date().toISOString(),
    pages: [{
      id: pageId,
      name: "Page 1",
      diagramType: "flowchart",
      nodes: [],
      edges: [],
    }],
  };
}

export function validateDiagramDocument(value: unknown): DiagramDocument {
  return diagramDocumentSchema.parse(value);
}
