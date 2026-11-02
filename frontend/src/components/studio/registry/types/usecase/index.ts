import { PluginNode } from "../shared";
import type { DiagramTypeDefinition } from "../../definition";
import { validateUseCase } from "./rules";

const definition: DiagramTypeDefinition = {
  id: "usecase",
  label: "Use Case",
  icon: "users",
  description: "Map actors, goals, and system interactions.",
  palette: [{
    id: "usecase",
    label: "Use Case",
    items: [
      { id: "actor", label: "Actor", nodeType: "actor" },
      { id: "use-case", label: "Use Case", nodeType: "use-case" },
      { id: "system-boundary", label: "System Boundary", nodeType: "system-boundary" },
    ],
  }],
  nodeTypes: { actor: PluginNode, "use-case": PluginNode, "system-boundary": PluginNode },
  edgeTypes: { association: {}, include: {}, extend: {} },
  connectionRules: [],
  validateDocument: validateUseCase,
  templates: ["ticketing-system"],
  ai: { enabled: false, systemPrompt: "" },
  defaultStyles: { node: "rounded" },
  quickAdd: { actor: ["use-case"], "use-case": ["actor", "use-case"] },
};

export default definition;
