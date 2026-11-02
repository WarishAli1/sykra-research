import type { DiagramDocument } from "./document";

export type FlowchartIssue = {
  id: string;
  message: string;
  targetIds: string[];
};

export function validateFlowchartConnections(document: DiagramDocument): FlowchartIssue[] {
  const page = document.pages.find((item) => item.id === document.activePageId) ?? document.pages[0];
  const ids = new Set(page.nodes.map((node) => node.id));
  return page.edges
    .filter((edge) => !ids.has(edge.source) || !ids.has(edge.target) || edge.source === edge.target)
    .map((edge) => ({
      id: `flowchart-invalid-edge-${edge.id}`,
      message: "Connections must join two different shapes.",
      targetIds: [edge.id, edge.source, edge.target],
    }));
}
