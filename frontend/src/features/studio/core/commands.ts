import type { DiagramDocument, DiagramEdge, DiagramNode } from "./document";

export type DiagramCommand =
  | { type: "add-node"; pageId: string; node: DiagramNode }
  | { type: "remove-edge"; pageId: string; edge: DiagramEdge }
  | { type: "dismiss-issue"; issueId: string };

export function applyCommand(document: DiagramDocument, command: DiagramCommand): DiagramDocument {
  if (command.type === "dismiss-issue") {
    return { ...document, dismissedIssues: [...new Set([...document.dismissedIssues, command.issueId])] };
  }
  return {
    ...document,
    pages: document.pages.map((page) => {
      if (page.id !== command.pageId) return page;
      if (command.type === "add-node") return { ...page, nodes: [...page.nodes, command.node] };
      return { ...page, edges: page.edges.filter((edge) => edge.id !== command.edge.id) };
    }),
    updatedAt: new Date().toISOString(),
  };
}
