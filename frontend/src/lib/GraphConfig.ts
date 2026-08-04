export const GRAPH_CONFIG = {
  palette: [
    "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#22d3ee", "#a78bfa",
    "#84cc16", "#f472b6", "#fb923c", "#34d399", "#60a5fa", "#e879f9",
  ],
  paperFallbackColor: "#7c8aa0",
  conceptFallbackColor: "#94a3b8",
  methodColor: "#f59e0b",
  datasetColor: "#22d3ee",
  edgeColors: {
    uses: "#f59e0b", evaluates: "#22d3ee", similar: "#6366f1", cites: "#ef4444",
  } as Record<string, string>,
  glowMultiplier: 3.0,
  labelZoomThreshold: 2.1,
  hubLabelDegree: 5,
  linkLabelZoom: 1.5,
  linkDistance: { similar: 40, cites: 34, discusses: 26, uses: 22, evaluates: 22 } as Record<string, number>,
  chargeStrength: -120,
  dashForWeight(w: number): number[] | null {
    if (w >= 0.75) return null;    
    if (w >= 0.60) return [4, 2];   
    return [2, 2];                 
  },
};