import { PluginNode } from "../shared";
import type { DiagramTypeDefinition } from "../../definition";
import { validate } from "./rules";

const definition: DiagramTypeDefinition = {
  id: "architecture", label: "Architecture", icon: "layers", description: "Describe systems, services, data, and boundaries.",
  palette: [
    { id: "clients", label: "Clients", items: [{ id: "web", label: "Web", nodeType: "client" }, { id: "mobile", label: "Mobile", nodeType: "client" }, { id: "desktop", label: "Desktop", nodeType: "client" }] },
    { id: "services", label: "Services", items: [{ id: "api", label: "API", nodeType: "service" }, { id: "worker", label: "Worker", nodeType: "service" }, { id: "queue", label: "Queue", nodeType: "service" }] },
    { id: "data", label: "Data", items: [{ id: "database", label: "Database", nodeType: "database" }, { id: "cache", label: "Cache", nodeType: "database" }] },
    { id: "boundary", label: "Container / Boundary", items: [{ id: "boundary", label: "Boundary", nodeType: "boundary" }] },
  ],
  nodeTypes: { client: PluginNode, service: PluginNode, database: PluginNode, boundary: PluginNode },
  edgeTypes: { sync: {}, async: {}, dependency: {}, "data-flow": {} },
  connectionRules: [],
  validateDocument: validate,
  templates: ["three-tier-web-app", "event-driven-system"],
  ai: { enabled: false, systemPrompt: "" },
  defaultStyles: { edge: "sync" },
  quickAdd: { client: ["service"], service: ["database", "service"], database: ["service"] },
};

export default definition;
