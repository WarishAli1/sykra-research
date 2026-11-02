import type { DiagramNodeComponent, DiagramTypeDefinition } from "./definition";

const definitions = new Map<string, DiagramTypeDefinition>();
let globalNodeTypesPromise: Promise<Record<string, DiagramNodeComponent>> | undefined;

export async function loadGlobalNodeTypes(): Promise<Record<string, DiagramNodeComponent>> {
  globalNodeTypesPromise ??= import("./types/chart").then((module) => ({ chart: module.ChartNodeComponent }));
  return globalNodeTypesPromise;
}

export function register(definition: DiagramTypeDefinition) {
  if (definitions.has(definition.id)) throw new Error(`Diagram type already registered: ${definition.id}`);
  const nodeTypes = new Set(Object.keys(definition.nodeTypes));
  for (const group of definition.palette) {
    for (const item of group.items) {
      if (item.nodeType && !nodeTypes.has(item.nodeType)) {
        throw new Error(`Palette item ${item.id} references missing node type ${item.nodeType}`);
      }
    }
  }
  definitions.set(definition.id, definition);
}

export function get(id: string) {
  return definitions.get(id);
}

export function list() {
  return [...definitions.values()];
}

export async function loadDiagramType(id: string): Promise<DiagramTypeDefinition> {
  if (definitions.has(id)) return definitions.get(id)!;
  const modules: Record<string, () => Promise<{ default: DiagramTypeDefinition }>> = {
    flowchart: () => import("./types/flowchart"),
    dfd: () => import("./types/dfd"),
    architecture: () => import("./types/architecture"),
    usecase: () => import("./types/usecase"),
  };
  const loader = modules[id];
  if (!loader) throw new Error(`Unknown diagram type: ${id}`);
  const pluginModule = await loader();
  register(pluginModule.default);
  return pluginModule.default;
}
