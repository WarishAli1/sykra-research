import { PluginNode } from "../shared";
import type { DiagramTypeDefinition } from "../../definition";
import { validateFlowchartConnections } from "../../../core/rules";

const definition: DiagramTypeDefinition = {
  id: "flowchart",
  label: "Flowchart",
  icon: "workflow",
  description: "Map steps, decisions, and outcomes.",
  palette: [{ id: "flowchart", label: "Flowchart", items: [
    { id: "start", label: "Start / End", nodeType: "start" },
    { id: "process", label: "Process", nodeType: "process" },
    { id: "decision", label: "Decision", nodeType: "decision" },
    { id: "data", label: "Data", nodeType: "data" },
  ] }],
  nodeTypes: { start: PluginNode, process: PluginNode, decision: PluginNode, data: PluginNode },
  edgeTypes: { smoothstep: {} },
  connectionRules: [],
  validateDocument: (document) => validateFlowchartConnections(document).map((issue) => ({
    ...issue,
    severity: "warning" as const,
    ruleId: "flowchart-valid-connection",
  })),
  templates: ["login-flow", "approval-flow"],
  ai: { enabled: false, systemPrompt: "" },
  defaultStyles: { node: "rounded" },
  quickAdd: { start: ["process"], process: ["process", "decision"], decision: ["process", "end"] },
};

export default definition;
