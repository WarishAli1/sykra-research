import { describe, expect, it } from "vitest";
import { createFlowchartDocument } from "../../../core/document";
import { validate } from "./rules";
import type { DiagramEdge } from "../../../core/document";

function documentWith(nodes: Array<{ id: string; type: "process" | "store" | "external"; label: string }>, edges: DiagramEdge[] = []) {
  const document = createFlowchartDocument();
  return {
    ...document,
    pages: [{ ...document.pages[0], diagramType: "dfd" as const, nodes: nodes.map((node) => ({ ...node, position: { x: 0, y: 0 } })), edges }],
  };
}

describe("DFD rules", () => {
  it("warns when a data flow has no label", () => {
    const issues = validate(documentWith(
      [{ id: "p", type: "process", label: "Process" }, { id: "e", type: "external", label: "User" }],
      [{ id: "flow", source: "e", target: "p" }],
    ));
    expect(issues.some((issue) => issue.ruleId === "dfd-labeled-flow")).toBe(true);
  });

  it("rejects entity-to-store connections", () => {
    const issues = validate(documentWith(
      [{ id: "e", type: "external", label: "User" }, { id: "s", type: "store", label: "Store" }],
      [{ id: "flow", source: "e", target: "s", label: "bad" }],
    ));
    expect(issues.some((issue) => issue.ruleId === "dfd-valid-pair")).toBe(true);
  });

  it("warns about processes without input and output", () => {
    const issues = validate(documentWith([{ id: "p", type: "process", label: "Process" }]));
    expect(issues.some((issue) => issue.ruleId === "dfd-process-input-output")).toBe(true);
  });
});
