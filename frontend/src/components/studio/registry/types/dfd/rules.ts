import type { DiagramIssue } from "../../definition";
import type { DiagramDocument, DiagramEdge, DiagramNode, DiagramPage } from "../../../core/document";

const invalidPairs = new Set(["store:store", "external:external", "external:store", "store:external"]);

export function connectionRules(page: DiagramPage, source: DiagramNode, target: DiagramNode, edge: DiagramEdge): DiagramIssue[] {
  const issues: DiagramIssue[] = [];
  if (source.id === target.id || invalidPairs.has(`${source.type}:${target.type}`)) {
    issues.push({ id: `dfd-pair-${edge.id}`, severity: "warning", message: "A data flow must include a Process.", targetIds: [edge.id, source.id, target.id], ruleId: "dfd-valid-pair", quickFix: { label: "Remove connection", command: { type: "remove-edge", pageId: page.id, edge } } });
  }
  if (!edge.label?.trim()) {
    issues.push({ id: `dfd-label-${edge.id}`, severity: "warning", message: "Data flows need a label.", targetIds: [edge.id], ruleId: "dfd-labeled-flow", quickFix: { label: "Add label", command: { type: "update-edge", pageId: page.id, edgeId: edge.id, patch: { label: "Data flow" } } } });
  }
  return issues;
}

export function validate(document: DiagramDocument): DiagramIssue[] {
  const page = document.pages.find((item) => item.id === document.activePageId) ?? document.pages[0];
  const issues: DiagramIssue[] = [];
  const nodesById = new Map(page.nodes.map((node) => [node.id, node]));
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, number>();
  const names = new Map<string, string[]>();
  for (const node of page.nodes) {
    incoming.set(node.id, 0); outgoing.set(node.id, 0);
    names.set(node.label.toLowerCase(), [...(names.get(node.label.toLowerCase()) ?? []), node.id]);
  }
  for (const edge of page.edges) {
    const source = nodesById.get(edge.source);
    const target = nodesById.get(edge.target);
    if (!source || !target) continue;
    outgoing.set(source.id, (outgoing.get(source.id) ?? 0) + 1);
    incoming.set(target.id, (incoming.get(target.id) ?? 0) + 1);
    issues.push(...connectionRules(page, source, target, edge));
  }
  for (const node of page.nodes) {
    if (node.type === "process" && (!incoming.get(node.id) || !outgoing.get(node.id))) {
      issues.push({ id: `dfd-process-${node.id}`, severity: "warning", message: "Every Process should have an input and an output.", targetIds: [node.id], ruleId: "dfd-process-input-output" });
    }
    if (node.type === "store" && (!incoming.get(node.id) || !outgoing.get(node.id))) {
      issues.push({ id: `dfd-store-${node.id}`, severity: "info", message: "Data Store should have a reader and a writer.", targetIds: [node.id], ruleId: "dfd-store-reader-writer" });
    }
  }
  for (const ids of names.values()) if (ids.length > 1) issues.push({ id: `dfd-duplicate-${ids.join("-")}`, severity: "warning", message: "Node names should be unique.", targetIds: ids, ruleId: "dfd-unique-names" });
  return issues;
}
