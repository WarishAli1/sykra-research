import { describe, expect, it } from "vitest";
import { get, list, register } from "./registry";
import type { DiagramTypeDefinition } from "./definition";

const dummy: DiagramTypeDefinition = {
  id: "flowchart",
  label: "Duplicate",
  icon: "test",
  description: "test",
  palette: [],
  nodeTypes: {},
  edgeTypes: {},
  connectionRules: [],
  validateDocument: () => [],
  templates: [],
  ai: { enabled: false, systemPrompt: "" },
  defaultStyles: {},
  quickAdd: {},
};

describe("diagram registry", () => {
  it("rejects duplicate ids", async () => {
    const flowchart = (await import("./types/flowchart")).default;
    register(flowchart);
    expect(get("flowchart")).toBe(flowchart);
    expect(() => register(dummy)).toThrow(/already registered/);
  });

  it("loads plugin definitions lazily", async () => {
    const dfd = (await import("./types/dfd")).default;
    register(dfd);
    expect(list().map((item) => item.id)).toContain("dfd");
  });

  it("supports a dummy plugin without changing core", () => {
    const testPlugin = { ...dummy, id: "test" as const, label: "Test" } as DiagramTypeDefinition;
    register(testPlugin);
    expect(get("test")?.label).toBe("Test");
  });

  it("rejects palette references to missing node types", () => {
    expect(() => register({
      ...dummy,
      id: "invalid",
      palette: [{ id: "bad", label: "Bad", items: [{ id: "missing", label: "Missing", nodeType: "process" }] }],
    })).toThrow(/missing node type/);
  });
});
