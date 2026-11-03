import type { DiagramDocument, DiagramEdge, DiagramNode } from "./document";

export type DrawioImportReport = {
  document: DiagramDocument;
  converted: number;
  skipped: string[];
};

export function exportMermaid(document: DiagramDocument): string {
  const page = document.pages.find((item) => item.id === document.activePageId) ?? document.pages[0];
  const lines = ["flowchart TD"];
  for (const node of page.nodes) {
    const safe = node.label.replace(/["[\]()]/g, "");
    lines.push(`  ${node.id}["${safe}"]`);
  }
  for (const edge of page.edges) {
    const label = edge.label ? `|${edge.label.replace(/[|]/g, "")}|` : "";
    lines.push(`  ${edge.source} -->${label} ${edge.target}`);
  }
  return lines.join("\n");
}

export function importDrawio(xml: string, base: DiagramDocument): DrawioImportReport {
  const parsed = new DOMParser().parseFromString(xml, "text/xml");
  const cells = [...parsed.querySelectorAll("mxCell")];
  const nodes: DiagramNode[] = [];
  const edges: DiagramEdge[] = [];
  const skipped: string[] = [];
  for (const cell of cells) {
    const id = cell.getAttribute("id");
    if (!id || id === "0" || id === "1") continue;
    const value = cell.getAttribute("value")?.trim() || "Untitled";
    if (cell.getAttribute("edge") === "1") {
      const source = cell.getAttribute("source");
      const target = cell.getAttribute("target");
      if (!source || !target) skipped.push(`Edge ${id} is missing a source or target.`);
      else edges.push({ id, source, target, label: value === "Untitled" ? undefined : value });
      continue;
    }
    const geometry = cell.querySelector("mxGeometry");
    nodes.push({ id, type: "process" as const, label: value, position: { x: Number(geometry?.getAttribute("x") ?? 0), y: Number(geometry?.getAttribute("y") ?? 0) } });
  }
  return {
    document: { ...base, pages: base.pages.map((page, index) => index === 0 ? { ...page, nodes, edges } : page), updatedAt: new Date().toISOString() },
    converted: nodes.length + edges.length,
    skipped,
  };
}

export function printPdf(document: DiagramDocument): void {
  if (typeof window === "undefined") throw new Error("PDF export requires a browser.");
  window.print();
}

export type DiagramSnapshot = { id: string; createdAt: string; document: DiagramDocument };

export function addSnapshot(snapshots: DiagramSnapshot[], document: DiagramDocument, limit = 10): DiagramSnapshot[] {
  return [{ id: crypto.randomUUID(), createdAt: new Date().toISOString(), document }, ...snapshots].slice(0, limit);
}
