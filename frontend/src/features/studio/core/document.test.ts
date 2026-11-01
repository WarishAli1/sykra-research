import { describe, expect, it } from "vitest";
import { createFlowchartDocument, validateDiagramDocument } from "./document";
import { migrateDiagramDocument } from "./migrations";
import { applyCommand } from "./commands";
import { validateFlowchartConnections } from "./rules";

describe("diagram documents", () => {
  it("creates and validates a v2 flowchart", () => {
    const document = createFlowchartDocument();
    expect(validateDiagramDocument(document)).toEqual(document);
  });

  it("migrates a Phase 1 v1 flowchart", () => {
    const document = migrateDiagramDocument({
      schemaVersion: 1,
      id: "doc",
      title: "Legacy",
      activePageId: "page",
      updatedAt: new Date().toISOString(),
      pages: [{ id: "page", name: "Page 1", nodes: [], edges: [] }],
    });
    expect(document.schemaVersion).toBe(2);
    expect(document.pages[0].diagramType).toBe("flowchart");
    expect(document.dismissedIssues).toEqual([]);
  });

  it("applies undoable commands and validates flowchart connections", () => {
    const document = createFlowchartDocument();
    const pageId = document.activePageId;
    const next = applyCommand(document, {
      type: "add-node",
      pageId,
      node: { id: "node", type: "process", position: { x: 0, y: 0 }, label: "Process" },
    });
    expect(next.pages[0].nodes).toHaveLength(1);
    const invalid = applyCommand(next, {
      type: "remove-edge",
      pageId,
      edge: { id: "edge", source: "node", target: "node" },
    });
    expect(validateFlowchartConnections({
      ...invalid,
      pages: [{ ...invalid.pages[0], edges: [{ id: "edge", source: "node", target: "node" }] }],
    })).toHaveLength(1);
  });
});
