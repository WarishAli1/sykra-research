import type { DiagramDocument } from "./document";

export type ExportOptions = {
  background: "light" | "dark" | "transparent";
  scale: 1 | 2 | 3 | 4;
};

const backgrounds = { light: "#ffffff", dark: "#051f20", transparent: "transparent" };

export function documentToSvg(document: DiagramDocument, options: ExportOptions): string {
  const page = document.pages.find((item) => item.id === document.activePageId) ?? document.pages[0];
  const width = 1200 * options.scale;
  const height = 800 * options.scale;
  const fill = backgrounds[options.background];
  const nodes = page.nodes.map((node) =>
    `<g><rect x="${node.position.x}" y="${node.position.y}" width="160" height="56" rx="10" fill="${node.style?.fill ?? (options.background === "dark" ? "#163832" : "#ffffff")}" stroke="#0e6b62"/><text x="${node.position.x + 80}" y="${node.position.y + 33}" text-anchor="middle" font-family="sans-serif" font-size="14" fill="${options.background === "dark" ? "#ffffff" : "#14181b"}">${escapeXml(node.label)}</text></g>`
  ).join("");
  const edges = page.edges.map((edge) => {
    const source = page.nodes.find((node) => node.id === edge.source);
    const target = page.nodes.find((node) => node.id === edge.target);
    if (!source || !target) return "";
    return `<path d="M ${source.position.x + 80} ${source.position.y + 56} L ${target.position.x + 80} ${target.position.y}" fill="none" stroke="#527066" marker-end="url(#arrow)"/>`;
  }).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 1200 800"><rect width="1200" height="800" fill="${fill}"/><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#527066"/></marker></defs>${edges}${nodes}</svg>`;
}

export async function exportPng(document: DiagramDocument, options: ExportOptions): Promise<Blob> {
  const svg = documentToSvg(document, options);
  const image = new Image();
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  await image.decode();
  const canvas = window.document.createElement("canvas");
  canvas.width = 1200 * options.scale;
  canvas.height = 800 * options.scale;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas export is unavailable.");
  context.drawImage(image, 0, 0);
  return new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("PNG export failed.")), "image/png"));
}

function escapeXml(value: string) {
  return value.replace(/[<>&'"]/g, (character) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", "\"": "&quot;" }[character] ?? character));
}
