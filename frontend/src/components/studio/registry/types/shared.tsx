import type { NodeProps } from "@xyflow/react";

export function PluginNode({ data, selected }: NodeProps) {
  const nodeData = data as { label?: string; kind?: string };
  return (
    <div className={`min-w-32 rounded-xl border border-line bg-white px-5 py-3 text-center text-sm shadow-soft ${selected ? "ring-2 ring-accent" : ""}`}>
      {nodeData.label ?? nodeData.kind ?? "Untitled"}
    </div>
  );
}
