import type { DiagramIssue } from "../../definition";
import type { DiagramDocument } from "../../../core/document";

export function validateUseCase(document: DiagramDocument): DiagramIssue[] {
  const page = document.pages.find((item) => item.id === document.activePageId) ?? document.pages[0];
  const issues: DiagramIssue[] = [];
  const ids = new Set(page.nodes.map((node) => node.id));
  for (const edge of page.edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) {
      issues.push({
        id: `usecase-orphan-edge-${edge.id}`,
        severity: "warning",
        message: "This relationship points to a missing element.",
        targetIds: [edge.id],
        ruleId: "usecase-orphan-edge",
      });
    }
  }
  for (const node of page.nodes.filter((item) => item.type === "use-case")) {
    const connected = page.edges.some((edge) => edge.source === node.id || edge.target === node.id);
    if (!connected) {
      issues.push({
        id: `usecase-isolated-${node.id}`,
        severity: "info",
        message: "This use case has no actor or relationship.",
        targetIds: [node.id],
        ruleId: "usecase-isolated",
      });
    }
  }
  return issues;
}
