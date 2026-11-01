import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

function filesUnder(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : path.endsWith(".ts") || path.endsWith(".tsx") ? [path] : [];
  });
}

describe("registry boundaries", () => {
  it("keeps core independent from concrete plugins", () => {
    const root = join(process.cwd(), "src/features/studio/core");
    const imports = filesUnder(root).flatMap((file) => readFileSync(file, "utf8").match(/registry\/types\//g) ?? []);
    expect(imports).toEqual([]);
  });
});
