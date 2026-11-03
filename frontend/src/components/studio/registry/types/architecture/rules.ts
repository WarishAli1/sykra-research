import type { DiagramIssue } from "../../definition";
import type { DiagramDocument } from "../../../core/document";

export function validate(document: DiagramDocument): DiagramIssue[] {
  const page = document.pages.find((item) => item.id === document.activePageId) ?? document.pages[0];
  const nodeMap = new Map(page.nodes.map((node) => [node.id, node]));
  const connected = new Set(page.edges.flatMap((edge) => [edge.source, edge.target]));
  const issues: DiagramIssue[] = [];
  for (const node of page.nodes) {
    if (!connected.has(node.id)) issues.push({ id: `architecture-isolated-${node.id}`, severity: "info", message: "This component is isolated.", targetIds: [node.id], ruleId: "architecture-isolated" });
  }
  for (const edge of page.edges) {
    const source = nodeMap.get(edge.source);
    const target = nodeMap.get(edge.target);
    if ((source?.type === "database" && target?.type === "client") || (source?.type === "client" && target?.type === "database")) {
      issues.push({ id: `architecture-direct-db-${edge.id}`, severity: "warning", message: "A Database should not connect directly to a Client.", targetIds: [edge.id, source.id, target.id], ruleId: "architecture-no-direct-client-db" });
    }
  }
  return issues;
}
