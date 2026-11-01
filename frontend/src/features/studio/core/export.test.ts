import { describe, expect, it } from "vitest";
import { createFlowchartDocument } from "./document";
import { documentToSvg } from "./export";

describe("diagram export", () => {
  it.each(["light", "dark", "transparent"] as const)("exports %s SVG with scale", (background) => {
    const svg = documentToSvg(createFlowchartDocument(), { background, scale: 2 });
    expect(svg).toContain('width="2400"');
    expect(svg).toContain(`fill="${background === "light" ? "#ffffff" : background === "dark" ? "#051f20" : "transparent"}"`);
  });
});
