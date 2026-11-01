import { describe, expect, it } from "vitest";
import { createFlowchartDocument } from "../../../core/document";
import { validate } from "./rules";

describe("architecture rules", () => {
  it("reports isolated components", () => {
    const document = createFlowchartDocument();
    const issues = validate({
      ...document,
      pages: [{ ...document.pages[0], diagramType: "architecture", nodes: [{ id: "db", type: "database", position: { x: 0, y: 0 }, label: "Database" }], edges: [] }],
    });
    expect(issues[0].ruleId).toBe("architecture-isolated");
  });

  it("warns about direct client database links", () => {
    const document = createFlowchartDocument();
    const issues = validate({
      ...document,
      pages: [{ ...document.pages[0], diagramType: "architecture", nodes: [
        { id: "client", type: "client", position: { x: 0, y: 0 }, label: "Web" },
        { id: "db", type: "database", position: { x: 0, y: 0 }, label: "Database" },
      ], edges: [{ id: "edge", source: "client", target: "db" }] }],
    });
    expect(issues.some((issue) => issue.ruleId === "architecture-no-direct-client-db")).toBe(true);
  });
});
