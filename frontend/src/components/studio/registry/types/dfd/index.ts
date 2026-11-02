import { PluginNode } from "../shared";
import type { DiagramTypeDefinition } from "../../definition";
import { connectionRules, validate } from "./rules";

const definition: DiagramTypeDefinition = {
  id: "dfd", label: "Data Flow Diagram", icon: "network", description: "Show how data moves between processes, stores, and entities.",
  palette: [{ id: "dfd", label: "Gane-Sarson", items: [
    { id: "external", label: "External Entity", nodeType: "external" },
    { id: "process", label: "Process", nodeType: "process" },
    { id: "store", label: "Data Store", nodeType: "store" },
    { id: "flow", label: "Data Flow", edgeType: "data-flow" },
    { id: "note", label: "Text / Note", nodeType: "note" },
  ] }],
  nodeTypes: { external: PluginNode, process: PluginNode, store: PluginNode, note: PluginNode },
  edgeTypes: { "data-flow": {} },
  connectionRules: [(page, source, target, edge) => connectionRules(page, source, target, edge)[0] ?? null],
  validateDocument: validate,
  templates: ["context-diagram", "order-system-level-1"],
  ai: { enabled: false, systemPrompt: "" },
  defaultStyles: { notation: "gane-sarson" },
  quickAdd: { process: ["store", "external", "process"], external: ["process"], store: ["process"] },
};

export default definition;
